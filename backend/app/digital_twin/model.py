"""Independent physics model used by the digital twin.

Deliberately *not* the simulator's code path:
* parameters come from the "design datasheet" (``TwinParams``) and differ from
  the true plant by a few percent (realistic model error),
* the state is integrated with RK4 on its own state vector,
* inputs are the commands the control system *issued* (approved setpoints plus
  the watermark offset obtained from the trusted watermark engine) and a small
  set of measured inputs (heater power, fan speed, generator power).

The model never reads ``Plant.physical``.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

STATE_KEYS = ("T_b", "T_hl", "T_cl", "T_so", "T_si", "m", "m_s")


@dataclass
class TwinParams:
    cp_lm: float = 1.25
    m_boiler: float = 1550.0
    m_hotleg: float = 62.0
    m_ihx: float = 390.0
    ua_loss: float = 0.62
    heater_max_kw: float = 2500.0
    pump_h0: float = 4.05
    pump_kp: float = 0.002
    k_sys: float = 0.0041
    k_valve: float = 0.001
    tau_flow: float = 1.25
    p_cover0: float = 1.5
    p_cover_beta: float = 0.0059
    t_ref: float = 400.0
    ua_hx: float = 8.2
    cp_w: float = 4.4
    m_s_max: float = 13.9
    tau_s_flow: float = 1.5
    m_so: float = 255.0
    m_si: float = 410.0
    ua_cool0: float = 5.1
    gen_eff: float = 0.30
    t_amb: float = 30.0

    def to_dict(self) -> dict:
        return asdict(self)


def eps_ntu(ua: float, c_a: float, c_b: float) -> tuple[float, float]:
    c_min, c_max = (c_a, c_b) if c_a < c_b else (c_b, c_a)
    if c_min <= 1e-6:
        return 0.0, 0.0
    ntu = ua / c_min
    cr = c_min / c_max
    if abs(1 - cr) < 1e-6:
        return ntu / (1 + ntu), c_min
    e = math.exp(-ntu * (1 - cr))
    return (1 - e) / (1 - cr * e), c_min


class HydraulicsModel:
    """Primary-loop hydraulics only (used for watermark response prediction)."""

    def __init__(self, p: TwinParams, m0: float):
        self.p = p
        self.m = m0

    def m_ss(self, speed_pct: float, valve_pct: float) -> float:
        p = self.p
        v = max(valve_pct / 100.0, 0.05)
        k_tot = p.pump_kp + p.k_sys + p.k_valve / (v * v)
        return max(0.0, speed_pct / 100.0) * math.sqrt(p.pump_h0 / k_tot)

    def step(self, dt: float, speed_pct: float, valve_pct: float) -> float:
        target = self.m_ss(speed_pct, valve_pct)
        self.m += (target - self.m) * (1.0 - math.exp(-dt / self.p.tau_flow))
        return self.m

    def p_dis(self, speed_pct: float, p_cover: float) -> float:
        s = speed_pct / 100.0
        return p_cover + self.p.pump_h0 * s * s - self.p.pump_kp * self.m * self.m


class TwinPhysics:
    def __init__(self, params: TwinParams):
        self.p = params
        self.x = {k: 0.0 for k in STATE_KEYS}
        self.hx_scale = 1.0  # tunable model parameter (twin configuration)

    def derivs(self, x: dict, u: dict) -> dict:
        p = self.p
        c_p = max(x["m"], 1e-3) * p.cp_lm
        c_s = max(x["m_s"], 1e-3) * p.cp_w
        eps, c_min = eps_ntu(p.ua_hx * self.hx_scale, c_p, c_s)
        q_hx = eps * c_min * (x["T_hl"] - x["T_si"])
        q_loss = p.ua_loss * (x["T_b"] - p.t_amb)
        q_turb = max(0.0, u["gen_kw"]) / p.gen_eff
        fan = u["fan_pct"] / 100.0
        q_cool = p.ua_cool0 * (0.1 + 0.9 * fan) * (0.5 * (x["T_so"] + x["T_si"]) - p.t_amb)
        v = max(u["valve_pct"] / 100.0, 0.05)
        k_tot = p.pump_kp + p.k_sys + p.k_valve / (v * v)
        m_t = max(0.0, u["pump_pct"] / 100.0) * math.sqrt(p.pump_h0 / k_tot)
        ms_t = p.m_s_max * u["pump2_pct"] / 100.0
        return {
            "T_b": (u["heater_kw"] - c_p * (x["T_b"] - x["T_cl"]) - q_loss) / (p.m_boiler * p.cp_lm),
            "T_hl": (x["T_b"] - x["T_hl"]) * max(x["m"], 0.2) / p.m_hotleg,
            "T_cl": (c_p * (x["T_hl"] - x["T_cl"]) - q_hx) / (p.m_ihx * p.cp_lm),
            "T_so": (c_s * (x["T_si"] - x["T_so"]) + q_hx) / (p.m_so * p.cp_w),
            "T_si": (c_s * (x["T_so"] - x["T_si"]) - q_turb - q_cool) / (p.m_si * p.cp_w),
            "m": (m_t - x["m"]) / p.tau_flow,
            "m_s": (ms_t - x["m_s"]) / p.tau_s_flow,
        }

    def rk4(self, x: dict, u: dict, dt: float) -> dict:
        k1 = self.derivs(x, u)
        x2 = {k: x[k] + 0.5 * dt * k1[k] for k in x}
        k2 = self.derivs(x2, u)
        x3 = {k: x[k] + 0.5 * dt * k2[k] for k in x}
        k3 = self.derivs(x3, u)
        x4 = {k: x[k] + dt * k3[k] for k in x}
        k4 = self.derivs(x4, u)
        return {k: x[k] + dt / 6.0 * (k1[k] + 2 * k2[k] + 2 * k3[k] + k4[k]) for k in x}

    def outputs(self, x: dict, u: dict) -> dict:
        """Predicted sensor readings for a state."""
        p = self.p
        p_cover = p.p_cover0 + p.p_cover_beta * (x["T_b"] - p.t_ref)
        s = u["pump_pct"] / 100.0
        p_dis = p_cover + p.pump_h0 * s * s - p.pump_kp * x["m"] * x["m"]
        return {
            "TT-101": x["T_hl"], "TT-102": x["T_cl"], "TT-103": x["T_b"], "FT-101": x["m"], "PT-101": p_dis,
            "PT-102": p_cover, "TT-201": x["T_si"], "TT-202": x["T_so"], "FT-201": x["m_s"],
        }


# measured variable -> state variable it corrects (None = algebraic output, not corrected directly)
MEASUREMENT_STATE = {
    "TT-101": "T_hl", "TT-102": "T_cl", "TT-103": "T_b", "FT-101": "m", "TT-201": "T_si", "TT-202": "T_so",
    "FT-201": "m_s", "PT-101": None, "PT-102": None,
}


class ActuatorModel:
    """Datasheet model of a final element (rate limit + first-order lag)."""

    def __init__(self, value: float, rate_limit: float, tau: float, lo: float = 0.0, hi: float = 100.0):
        self.value = value
        self.rate_limit = rate_limit
        self.tau = tau
        self.lo, self.hi = lo, hi

    def step(self, dt: float, cmd: float) -> float:
        cmd = min(self.hi, max(self.lo, cmd))
        desired = self.value + (cmd - self.value) * min(1.0, dt / self.tau) if self.tau > 0 else cmd
        mx = self.rate_limit * dt
        self.value += max(-mx, min(mx, desired - self.value))
        return self.value


# Datasheet values the twin assumes for its actuator models (rate %/s, tau s)
ACTUATOR_DATASHEET = {"P-101": (6.0, 0.4), "FCV-101": (10.0, 0.3), "P-201": (6.0, 0.4)}
