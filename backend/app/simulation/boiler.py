"""Liquid-metal boiler, intermediate heat exchanger and secondary loop.

EDUCATIONAL SIMULATION ONLY.  The parameters are plausible, hypothetical values
chosen to give readable dynamics on a dashboard.  This is *not* a validated
nuclear, thermal-hydraulic or industrial engineering model and must not be used
for design or safety analysis.

Lumped-parameter model (explicit Euler with sub-stepping):

  Boiler vessel   C_b  dT_b/dt  = Q_heater - m*cp*(T_b - T_cl) - UA_loss*(T_b - T_amb)
  Hot leg         dT_hl/dt      = (T_b - T_hl) * m / M_hl            (transport lag)
  IHX primary     C_x  dT_cl/dt = m*cp*(T_hl - T_cl) - Q_hx
  IHX secondary   C_so dT_so/dt = C_s*(T_si - T_so) + Q_hx
  Heat sinks      C_si dT_si/dt = C_s*(T_so - T_si) - Q_turbine - Q_cooler
  Q_hx  = eps(NTU, Cr) * C_min * (T_hl - T_si)     (counter-flow effectiveness-NTU)

Hydraulics (primary): pump head  dP_pump = H0*s^2 - Kp*m^2, system dP = (Ksys + Kv/v^2) m^2,
flow relaxes to the operating point with time constant tau_flow.
Cover-gas pressure rises linearly with bulk temperature (thermal expansion).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from app.core.rng import NoiseStream
from app.core.util import clamp


@dataclass
class BoilerParams:
    cp_lm: float = 1.27  # kJ/(kg K) liquid-metal coolant (hypothetical, sodium-like)
    m_boiler: float = 1500.0  # kg effective inventory in the boiler vessel
    m_hotleg: float = 60.0  # kg in hot-leg piping (transport lag)
    m_ihx: float = 400.0  # kg primary-side IHX inventory
    ua_loss: float = 0.6  # kW/K vessel heat-loss conductance
    heater_max_kw: float = 2500.0
    pump_h0: float = 4.0  # bar shut-off head at 100 % speed
    pump_kp: float = 0.002  # bar/(kg/s)^2 pump internal loss
    k_sys: float = 0.004  # bar/(kg/s)^2 loop resistance
    k_valve: float = 0.001  # bar/(kg/s)^2 valve resistance when fully open
    tau_flow: float = 1.2  # s
    p_cover0: float = 1.5  # bar(g) cover gas at t_ref
    p_cover_beta: float = 0.006  # bar/K
    t_ref: float = 400.0
    ua_hx: float = 8.0  # kW/K IHX conductance
    cp_w: float = 4.4  # kJ/(kg K) pressurised secondary water
    m_s_max: float = 14.0  # kg/s secondary flow at 100 % pump speed
    tau_s_flow: float = 1.5
    m_so: float = 250.0  # kg secondary-side IHX inventory
    m_si: float = 400.0  # kg heat-sink inventory
    ua_cool0: float = 5.0  # kW/K air-cooler conductance at 100 % fan
    gen_eff: float = 0.30  # turbine-generator efficiency
    gen_tau: float = 2.0  # s
    gen_rated_kw: float = 450.0
    t_amb: float = 30.0

    def to_dict(self) -> dict:
        return asdict(self)


def ntu_effectiveness(ua: float, c_a: float, c_b: float) -> tuple[float, float]:
    """Counter-flow effectiveness. Returns (eps, C_min)."""
    c_min, c_max = (c_a, c_b) if c_a < c_b else (c_b, c_a)
    if c_min <= 1e-6:
        return 0.0, 0.0
    ntu = ua / c_min
    cr = c_min / c_max
    if abs(1.0 - cr) < 1e-6:
        return ntu / (1.0 + ntu), c_min
    e = math.exp(-ntu * (1.0 - cr))
    return (1.0 - e) / (1.0 - cr * e), c_min


def pump_flow_ss(p: BoilerParams, speed_frac: float, valve_frac: float) -> float:
    """Steady-state primary flow for a pump speed / valve opening (fractions)."""
    v = max(valve_frac, 0.05)
    k_tot = p.pump_kp + p.k_sys + p.k_valve / (v * v)
    return max(0.0, speed_frac) * math.sqrt(p.pump_h0 / k_tot)


def pump_dp(p: BoilerParams, speed_frac: float, m: float) -> float:
    return p.pump_h0 * speed_frac * speed_frac - p.pump_kp * m * m


def cover_pressure(p: BoilerParams, t_b: float) -> float:
    return p.p_cover0 + p.p_cover_beta * (t_b - p.t_ref)


class BoilerLoop:
    """True physical state of the primary + secondary loop (ground truth)."""

    def __init__(self, params: BoilerParams, disturbance: NoiseStream):
        self.p = params
        self.dist = disturbance
        self.T_b = 450.0
        self.T_hl = 450.0
        self.T_cl = 390.0
        self.T_so = 250.0
        self.T_si = 220.0
        self.m = 19.5
        self.m_s = 11.2
        self.Q_heater = 1700.0
        self.Q_hx = 1500.0
        self.Q_loss = 250.0
        self.Q_turb = 1000.0
        self.Q_cool = 500.0
        self.P_dis = 3.6
        self.P_cover = 1.8
        self.P_gen = 300.0
        self.gen_speed = 3000.0
        self.load_demand_kw = 300.0
        self.hx_fouling = 1.0  # multiplier on UA_hx (1.0 = clean); changed only by physical degradation

    # ------------------------------------------------------------------ physics
    def step(self, dt: float, heater_pct: float, pump_pct: float, valve_pct: float,
             pump2_pct: float, fan_pct: float, load_kw: float, substeps: int = 2) -> None:
        p = self.p
        h = dt / substeps
        # small process disturbance: heater supply-voltage ripple (+-0.4 %)
        heater_kw = p.heater_max_kw * clamp(heater_pct, 0, 100) / 100.0 * (1.0 + 0.004 * self.dist.next())
        s = clamp(pump_pct, 0, 100) / 100.0
        v = clamp(valve_pct, 0, 100) / 100.0
        s2 = clamp(pump2_pct, 0, 100) / 100.0
        fan = clamp(fan_pct, 0, 100) / 100.0
        self.load_demand_kw = load_kw
        m_target = pump_flow_ss(p, s, v)
        m_s_target = p.m_s_max * s2
        q_turb_target = max(0.0, load_kw) / p.gen_eff
        for _ in range(substeps):
            self.m += (m_target - self.m) * min(1.0, h / p.tau_flow)
            self.m_s += (m_s_target - self.m_s) * min(1.0, h / p.tau_s_flow)
            self.Q_heater += (heater_kw - self.Q_heater) * min(1.0, h / 2.0)
            c_p = max(self.m, 1e-3) * p.cp_lm
            c_s = max(self.m_s, 1e-3) * p.cp_w
            eps, c_min = ntu_effectiveness(p.ua_hx * self.hx_fouling, c_p, c_s)
            self.Q_hx = eps * c_min * (self.T_hl - self.T_si)
            self.Q_loss = p.ua_loss * (self.T_b - p.t_amb)
            # turbine draws heat only while the secondary is hot enough to make steam
            avail = max(0.0, (self.T_so - 150.0) / 60.0)
            self.Q_turb = q_turb_target * min(1.0, avail)
            t_mean_s = 0.5 * (self.T_so + self.T_si)
            self.Q_cool = p.ua_cool0 * (0.1 + 0.9 * fan) * (t_mean_s - p.t_amb)

            dT_b = (self.Q_heater - c_p * (self.T_b - self.T_cl) - self.Q_loss) / (p.m_boiler * p.cp_lm)
            dT_hl = (self.T_b - self.T_hl) * max(self.m, 0.2) / p.m_hotleg
            dT_cl = (c_p * (self.T_hl - self.T_cl) - self.Q_hx) / (p.m_ihx * p.cp_lm)
            dT_so = (c_s * (self.T_si - self.T_so) + self.Q_hx) / (p.m_so * p.cp_w)
            dT_si = (c_s * (self.T_so - self.T_si) - self.Q_turb - self.Q_cool) / (p.m_si * p.cp_w)
            self.T_b += h * dT_b
            self.T_hl += h * dT_hl
            self.T_cl += h * dT_cl
            self.T_so += h * dT_so
            self.T_si += h * dT_si
        self.P_dis = cover_pressure(p, self.T_b) + pump_dp(p, s, self.m)
        self.P_cover = cover_pressure(p, self.T_b)
        p_mech = self.Q_turb * p.gen_eff
        self.P_gen += (p_mech - self.P_gen) * min(1.0, dt / p.gen_tau)
        self.gen_speed = 3000.0 * (1.0 + 0.02 * (p_mech - self.P_gen) / p.gen_rated_kw)

    # ------------------------------------------------------------------ helpers
    def state(self) -> dict[str, float]:
        return {
            "boiler.T_b": self.T_b,
            "boiler.T_hl": self.T_hl,
            "boiler.T_cl": self.T_cl,
            "boiler.m": self.m,
            "boiler.P_dis": self.P_dis,
            "boiler.P_cover": self.P_cover,
            "boiler.Q_heater": self.Q_heater,
            "boiler.Q_hx": self.Q_hx,
            "boiler.Q_loss": self.Q_loss,
            "sec.T_so": self.T_so,
            "sec.T_si": self.T_si,
            "sec.m_s": self.m_s,
            "sec.Q_turb": self.Q_turb,
            "sec.Q_cool": self.Q_cool,
            "gen.P": self.P_gen,
            "gen.speed": self.gen_speed,
            "gen.freq": self.gen_speed / 60.0,
            "gen.load_demand": self.load_demand_kw,
        }

    def init_steady_state(self, t_hl_sp: float, t_si_sp: float, pump_pct: float, valve_pct: float,
                          pump2_pct: float, load_kw: float) -> dict[str, float]:
        """Closed-form design steady state; returns the actuator outputs that hold it."""
        p = self.p
        self.m = pump_flow_ss(p, pump_pct / 100.0, valve_pct / 100.0)
        self.m_s = p.m_s_max * pump2_pct / 100.0
        c_p = self.m * p.cp_lm
        c_s = self.m_s * p.cp_w
        eps, c_min = ntu_effectiveness(p.ua_hx * self.hx_fouling, c_p, c_s)
        self.T_b = self.T_hl = t_hl_sp
        self.T_si = t_si_sp
        self.Q_hx = eps * c_min * (t_hl_sp - t_si_sp)
        self.T_cl = t_hl_sp - self.Q_hx / c_p
        self.T_so = t_si_sp + self.Q_hx / c_s
        self.Q_loss = p.ua_loss * (self.T_b - p.t_amb)
        self.Q_heater = self.Q_hx + self.Q_loss
        self.Q_turb = load_kw / p.gen_eff
        self.Q_cool = self.Q_hx - self.Q_turb
        t_mean = 0.5 * (self.T_so + self.T_si)
        fan = (self.Q_cool / (p.ua_cool0 * (t_mean - p.t_amb)) - 0.1) / 0.9
        self.P_gen = load_kw
        self.load_demand_kw = load_kw
        self.P_cover = cover_pressure(p, self.T_b)
        self.P_dis = self.P_cover + pump_dp(p, pump_pct / 100.0, self.m)
        return {"heater_pct": 100.0 * self.Q_heater / p.heater_max_kw, "fan_pct": 100.0 * clamp(fan, 0, 1)}


def load_profile(t: float) -> float:
    """Electrical load demand on the turbine-generator (kW), compressed 'daily' cycle."""
    return 300.0 + 55.0 * math.sin(2 * math.pi * t / 240.0) + 20.0 * math.sin(2 * math.pi * t / 67.0 + 0.7)
