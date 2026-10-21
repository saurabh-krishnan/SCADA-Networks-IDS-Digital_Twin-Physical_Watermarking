"""Auxiliary plant subsystems built from the same reusable abstractions.

All models are simplified, educational, discrete-time approximations.

* ``InductionMotor``      – reusable VFD-driven motor (speed, current, winding temp, vibration)
* ``WaterTreatment``      – raw tank -> filter -> chlorination -> treated-water tank
* ``ChemicalMixing``      – batch reactor (fill A, fill B, react, drain) with an agitator motor
* ``PipelineTankFarm``    – transfer pump + pipeline + two remote storage tanks
"""
from __future__ import annotations

import math

from app.core.rng import NoiseStream
from app.core.util import clamp


class InductionMotor:
    def __init__(self, rated_rpm: float = 1480.0, rated_current: float = 42.0, no_load_current: float = 12.0,
                 tau: float = 1.5, t_amb: float = 30.0, vib_base: float = 0.6):
        self.rated_rpm = rated_rpm
        self.i_fl = rated_current
        self.i_nl = no_load_current
        self.tau = tau
        self.t_amb = t_amb
        self.vib_base = vib_base
        self.speed = 0.0
        self.current = 0.0
        self.winding_T = t_amb + 5
        self.vibration = 0.1
        self.load_factor = 1.0  # mechanical load multiplier

    def step(self, dt: float, cmd_pct: float) -> None:
        target = self.rated_rpm * clamp(cmd_pct, 0, 100) / 100.0
        accel = target - self.speed
        self.speed += accel * min(1.0, dt / self.tau)
        frac = self.speed / self.rated_rpm
        load = self.load_factor * frac ** 3  # affinity law for pump / agitator loads
        inrush = 0.6 * abs(accel) / self.rated_rpm if accel > 0 else 0.0
        if self.speed < 1.0:
            self.current = 0.0
        else:
            self.current = self.i_nl + (self.i_fl - self.i_nl) * load + self.i_fl * min(inrush, 3.0)
        heat = (self.current / self.i_fl) ** 2
        t_target = self.t_amb + 55.0 * heat
        self.winding_T += (t_target - self.winding_T) * min(1.0, dt / 240.0)
        self.vibration = 0.1 + self.vib_base * frac * frac


class WaterTreatment:
    AREA_RAW = 30.0  # m2
    AREA_TW = 40.0  # m2

    def __init__(self, dist: NoiseStream):
        self.dist = dist
        self.L_raw = 3.0
        self.L_tw = 4.0
        self.Q_filt = 60.0  # m3/h
        self.fouling = 0.2
        self.dP = 0.25
        self.turb_in = 4.0
        self.turb_out = 0.12
        self.cl = 1.0
        self.ph = 7.2
        self.backwash = False
        self.t = 0.0

    def demand(self, t: float) -> float:
        return 55.0 + 12.0 * math.sin(2 * math.pi * t / 300.0) + 5.0 * math.sin(2 * math.pi * t / 47.0)

    def step(self, dt: float, p301_pct: float, p302_pct: float, xv301_open: float, xv303_open: float) -> None:
        self.t += dt
        q_river = 95.0 * (1.0 if xv301_open > 50 else 0.0)
        q_pump = 110.0 * clamp(p301_pct, 0, 100) / 100.0
        self.backwash = xv303_open > 50
        if self.L_raw <= 0.2:
            q_pump = 0.0
        self.Q_filt += (q_pump - self.Q_filt) * min(1.0, dt / 3.0)
        to_tank = 0.0 if self.backwash else self.Q_filt
        self.L_raw = clamp(self.L_raw + dt * (q_river - self.Q_filt) / 3600.0 / self.AREA_RAW * 60.0, 0.0, 5.5)
        self.L_tw = clamp(self.L_tw + dt * (to_tank - self.demand(self.t)) / 3600.0 / self.AREA_TW * 60.0, 0.0, 6.0)
        self.turb_in = 4.0 + 1.2 * math.sin(2 * math.pi * self.t / 500.0) + 0.05 * self.dist.next()
        if self.backwash:
            self.fouling += (0.05 - self.fouling) * min(1.0, dt / 8.0)
        else:
            self.fouling += dt * self.Q_filt * self.turb_in * 1.4e-5
        self.dP = 0.12 + self.fouling * (self.Q_filt / 100.0) ** 2 * 1.6
        self.turb_out = 0.08 + 0.5 * max(0.0, self.fouling - 0.6) + (1.5 if self.backwash else 0.0) * 0.1
        # chlorine residual: dosing proportional to stroke / flow, first-order mixing, slow decay
        dose = 4.0 * clamp(p302_pct, 0, 100) / 100.0 * 60.0 / max(self.Q_filt, 5.0)
        self.cl += ((dose - 0.08) - self.cl) * min(1.0, dt / 25.0)
        self.cl = max(0.0, self.cl)
        self.ph += ((7.25 - 0.08 * self.cl) - self.ph) * min(1.0, dt / 40.0)

    def state(self) -> dict[str, float]:
        return {
            "wt.L_raw": self.L_raw, "wt.L_tw": self.L_tw, "wt.Q_filt": self.Q_filt, "wt.dP": self.dP,
            "wt.turb_out": self.turb_out, "wt.cl": self.cl, "wt.ph": self.ph,
            "wt.demand": self.demand(self.t), "wt.backwash": 1.0 if self.backwash else 0.0,
        }


class ChemicalMixing:
    """Batch reactor. Reagent A (acid) + reagent B (base) -> product, exothermic."""

    def __init__(self, dist: NoiseStream):
        self.dist = dist
        self.vol_a = 0.0  # % of tank volume
        self.vol_b = 0.0
        self.vol_p = 5.0
        self.T = 35.0
        self.motor = InductionMotor(rated_rpm=1450, rated_current=38, no_load_current=10, tau=2.0, vib_base=1.4)

    @property
    def level(self) -> float:
        return self.vol_a + self.vol_b + self.vol_p

    def step(self, dt: float, xv401: float, xv402: float, xv403: float, agit_pct: float, tcv401: float) -> None:
        self.motor.step(dt, agit_pct)
        if xv401 > 50:
            self.vol_a += 2.0 * dt
        if xv402 > 50:
            self.vol_b += 2.0 * dt
        lvl = self.level
        if xv403 > 50 and lvl > 0:
            out = min(lvl, 3.0 * dt)
            f = out / lvl
            self.vol_a -= self.vol_a * f
            self.vol_b -= self.vol_b * f
            self.vol_p -= self.vol_p * f
        mixing = self.motor.speed / self.motor.rated_rpm
        rate = 0.035 * mixing * min(self.vol_a, self.vol_b) * dt
        self.vol_a -= rate
        self.vol_b -= rate
        self.vol_p += 2 * rate
        heat = 2.2 * rate / max(dt, 1e-6) / max(self.level, 5.0) * 10.0
        cooling = 0.02 * clamp(tcv401, 0, 100) / 100.0 * (self.T - 20.0) * 10.0
        loss = 0.002 * (self.T - 30.0)
        self.T += dt * (heat - cooling - loss)

    def state(self) -> dict[str, float]:
        lvl = max(self.level, 1e-6)
        excess = (self.vol_b - self.vol_a) / lvl
        ph = 7.0 + 6.0 * math.tanh(3.0 * excess)
        return {
            "mix.level": self.level, "mix.T": self.T, "mix.ph": ph, "mix.conc": 100.0 * self.vol_p / lvl,
            "mix.agit_rpm": self.motor.speed, "mix.motor_I": self.motor.current,
            "mix.motor_T": self.motor.winding_T, "mix.motor_vib": self.motor.vibration,
        }


class PipelineTankFarm:
    AREA = 50.0  # m2 per tank

    def __init__(self, dist: NoiseStream):
        self.dist = dist
        self.Q = 80.0  # m3/h
        self.L1 = 5.0
        self.L2 = 4.0
        self.P1 = 6.5
        self.P2 = 2.4
        self.motor = InductionMotor(rated_rpm=2950, rated_current=95, no_load_current=25, tau=2.5, vib_base=1.0)
        self.t = 0.0

    def demand(self, t: float, tank: int) -> float:
        base = 38.0 if tank == 1 else 34.0
        return base + 8.0 * math.sin(2 * math.pi * t / (420.0 if tank == 1 else 360.0) + tank)

    def step(self, dt: float, p501_pct: float, xv501: float, xv502: float) -> None:
        self.t += dt
        self.motor.step(dt, p501_pct)
        frac = self.motor.speed / self.motor.rated_rpm
        open1, open2 = xv501 > 50, xv502 > 50
        k = 0.0 if not (open1 or open2) else 1.0
        q_target = 115.0 * frac * k
        self.Q += (q_target - self.Q) * min(1.0, dt / 4.0)
        self.P1 = 1.5 + 10.0 * frac * frac - 0.0003 * self.Q ** 2 + 0.02 * self.dist.next()
        self.P2 = max(0.0, self.P1 - 0.00035 * self.Q ** 2 - 0.2)
        q1 = self.Q * (1.0 if open1 and not open2 else 0.5 if open1 and open2 else 0.0)
        q2 = self.Q - q1 if (open1 or open2) else 0.0
        self.L1 = clamp(self.L1 + dt * (q1 - self.demand(self.t, 1)) / 3600.0 / self.AREA * 30.0, 0.0, 10.0)
        self.L2 = clamp(self.L2 + dt * (q2 - self.demand(self.t, 2)) / 3600.0 / self.AREA * 30.0, 0.0, 10.0)

    def state(self) -> dict[str, float]:
        return {
            "pipe.Q": self.Q, "pipe.P1": self.P1, "pipe.P2": self.P2, "pipe.L1": self.L1, "pipe.L2": self.L2,
            "pipe.motor_rpm": self.motor.speed, "pipe.motor_I": self.motor.current,
            "pipe.motor_T": self.motor.winding_T, "pipe.motor_vib": self.motor.vibration,
        }
