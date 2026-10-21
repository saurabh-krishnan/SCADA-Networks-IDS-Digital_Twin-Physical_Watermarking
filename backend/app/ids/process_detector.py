"""Process-layer detection on SCADA observations.

Rules: alarm limits, frozen values, implausible rate of change, setpoint deviation
from the operator-approved value, pump-flow inconsistency, actuator
command/feedback mismatch and energy-balance / redundancy violations.
"""
from __future__ import annotations

import math
from collections import deque

from app.digital_twin.model import TwinParams
from app.ids.base import Condition
from app.ids.consistency import BoilerConsistency

PUMP_CHECKS = [
    # pump, flow sensor, expected-flow function name
    ("P-101", "FT-101", "primary"),
    ("P-201", "FT-201", "secondary"),
    ("P-301", "FT-301", "filter"),
]


class _SensorState:
    __slots__ = ("last_t", "frozen_buf", "roc_buf", "frozen_n")

    def __init__(self, frozen_n: int, roc_n: int):
        self.last_t = -1.0
        self.frozen_n = frozen_n
        self.frozen_buf: deque = deque(maxlen=frozen_n)
        self.roc_buf: deque = deque(maxlen=roc_n)


class ProcessDetector:
    LAYER = "process"

    def __init__(self, sensors: list, actuator_kinds: dict[str, str], register_owner: dict[str, str]):
        self.sensors = {s.id: s for s in sensors}
        self.state: dict[str, _SensorState] = {}
        for s in sensors:
            hz = 10.0 / max(1, s.sample_every)
            fast = s.controller in ("PLC-1", "PLC-2")
            poll_hz = 10.0 if fast else 2.0
            eff = min(hz, poll_hz)
            self.state[s.id] = _SensorState(max(8, int(4.0 * eff)), max(4, int(2 * eff)))
        self.actuator_kinds = actuator_kinds
        self.register_owner = register_owner
        self.design = TwinParams()
        self.consistency = BoilerConsistency(TwinParams())
        self.sp_mismatch_since: dict[str, float] = {}
        self.fb_mismatch_since: dict[str, float] = {}
        self.pump_bad_since: dict[str, float] = {}
        self.eb_bad_since: float | None = None
        self.pump_hist: dict[str, deque] = {p: deque(maxlen=30) for p, _, _ in PUMP_CHECKS}
        self.evidence_cache: dict = {}

    # ------------------------------------------------------------------ expected flows (design curves)
    def expected_flow(self, kind: str, speed: float, valve: float = 80.0) -> float:
        d = self.design
        if kind == "primary":
            v = max(valve / 100.0, 0.05)
            k_tot = d.pump_kp + d.k_sys + d.k_valve / (v * v)
            return max(0.0, speed / 100.0) * math.sqrt(d.pump_h0 / k_tot)
        if kind == "secondary":
            return d.m_s_max * speed / 100.0
        return 110.0 * speed / 100.0

    def evaluate(self, t: float, scada, approved: dict[str, float]) -> list[Condition]:
        out: list[Condition] = []
        tags = scada.tags
        for sid, s in self.sensors.items():
            e = tags.get(sid)
            if not e:
                continue
            v, ts = e[0], e[1]
            st = self.state[sid]
            if ts == st.last_t:
                continue  # no new observation
            st.last_t = ts
            lvl = s.limits.classify(v)
            if lvl != "normal":
                out.append(Condition(self.LAYER, "PROC-LIMIT", sid, "medium" if lvl == "critical" else "low",
                                     "Process limit exceeded",
                                     {"tag": sid, "value": round(v, 4), "level": lvl, "limits": s.limits.to_dict(),
                                      "unit": s.unit}, 1.0 if lvl == "critical" else 0.6, 0.6,
                                     "Check process; operator action per alarm response manual", hold_s=3.0))
            st.frozen_buf.append(v)
            if s.noise_sigma > 0 and len(st.frozen_buf) == st.frozen_n:
                first = st.frozen_buf[0]
                at_range_limit = first <= s.range_lo or first >= s.range_hi  # e.g. stopped motor reads 0
                if not at_range_limit and all(x == first for x in st.frozen_buf):
                    out.append(Condition(self.LAYER, "PROC-FROZEN", sid, "high", "Frozen sensor value",
                                         {"tag": sid, "value": round(v, 4), "identical_samples": st.frozen_n,
                                          "expected_noise_sigma": s.noise_sigma,
                                          "detail": "consecutive identical readings from a noisy instrument"},
                                         1.0, 0.85, "Mark sensor suspicious; use twin estimate; check telemetry path",
                                         hold_s=4.0))
            st.roc_buf.append((ts, v))
            n = len(st.roc_buf)
            if n == st.roc_buf.maxlen and n >= 4:
                h = n // 2
                a = list(st.roc_buf)
                t1 = sum(p[0] for p in a[:h]) / h
                t2 = sum(p[0] for p in a[h:]) / (n - h)
                x1 = sum(p[1] for p in a[:h]) / h
                x2 = sum(p[1] for p in a[h:]) / (n - h)
                if t2 - t1 > 1e-6:
                    rate = (x2 - x1) / (t2 - t1)
                    if abs(rate) > s.max_rate:
                        out.append(Condition(self.LAYER, "PROC-ROC", sid, "medium", "Implausible process transition",
                                             {"tag": sid, "rate_per_s": round(rate, 4), "max_rate": s.max_rate,
                                              "unit": s.unit}, min(1.0, abs(rate) / (4 * s.max_rate)), 0.7,
                                             "Cross-check redundant instruments and the digital twin", hold_s=5.0))
        # setpoint deviation: PLC-reported holding register vs operator-approved value
        for reg, val in approved.items():
            e = tags.get(reg)
            if not e:
                continue
            tol = max(1e-3, 0.002 * max(abs(val), 1.0))
            if abs(e[0] - val) > tol:
                since = self.sp_mismatch_since.setdefault(reg, t)
                if t - since >= 1.0:
                    out.append(Condition(self.LAYER, "PROC-SP-MISMATCH", self.register_owner.get(reg, reg), "high",
                                         "Setpoint deviation from approved value",
                                         {"register": reg, "approved": round(val, 4), "reported": round(e[0], 4),
                                          "since": round(since, 2)}, 1.0, 0.9,
                                         "Restore the approved setpoint; enable write allow-list", hold_s=4.0))
            else:
                self.sp_mismatch_since.pop(reg, None)
        # actuator command vs feedback
        for aid, kind in self.actuator_kinds.items():
            c, f = tags.get(f"{aid}.CMD"), tags.get(f"{aid}.FB")
            if not c or not f:
                continue
            tol = 50.0 if kind == "onoff_valve" else 6.0
            if abs(c[0] - f[0]) > tol:
                since = self.fb_mismatch_since.setdefault(aid, t)
                if t - since >= 8.0:
                    out.append(Condition(self.LAYER, "PROC-ACT-FB", aid, "medium", "Unexpected actuator behavior",
                                         {"actuator": aid, "command": round(c[0], 3), "feedback": round(f[0], 3),
                                          "since": round(since, 2)}, 0.7, 0.6,
                                         "Inspect actuator; verify firmware / final element", hold_s=4.0))
            else:
                self.fb_mismatch_since.pop(aid, None)
        # pump-flow consistency (design pump curves, 3-s averages, steady speed only)
        for pump, ft, kind in PUMP_CHECKS:
            fb, fl = tags.get(f"{pump}.FB"), tags.get(ft)
            if not fb or not fl:
                continue
            valve = tags.get("FCV-101.FB", [80.0])[0] if kind == "primary" else 80.0
            hist = self.pump_hist[pump]
            hist.append((fb[0], fl[0], valve))
            if len(hist) < hist.maxlen:
                continue
            speeds = [h[0] for h in hist]
            if max(speeds) - min(speeds) > 4.0 or speeds[-1] < 5.0:
                self.pump_bad_since.pop(pump, None)
                continue
            sp = sum(speeds) / len(speeds)
            flow = sum(h[1] for h in hist) / len(hist)
            vv = sum(h[2] for h in hist) / len(hist)
            exp = self.expected_flow(kind, sp, vv)
            err = (flow - exp) / max(exp, 1e-3)
            if abs(err) > 0.12:
                since = self.pump_bad_since.setdefault(pump, t)
                if t - since >= 3.0:
                    out.append(Condition(self.LAYER, "PROC-PUMP-FLOW", pump, "high", "Pump-flow inconsistency",
                                         {"pump": pump, "flow_sensor": ft, "speed_fb_pct": round(sp, 2),
                                          "observed_flow": round(flow, 3), "expected_flow": round(exp, 3),
                                          "rel_error": round(err, 3)}, min(1.0, abs(err) / 0.4), 0.75,
                                         "Inspect pump / flow transmitter; compare with digital twin", hold_s=5.0))
            else:
                self.pump_bad_since.pop(pump, None)
        # energy balance / analytical redundancy on the boiler loop
        obs = {k: (tags[k][0], scada.quality(k, t) == "good") for k in BoilerConsistency.TAGS if k in tags}
        self.consistency.push(t, obs)
        c = self.consistency
        if c.ready:
            bad = []
            if abs(c.eb1) > 150.0:
                bad.append(("boiler energy balance", round(c.eb1, 1), "kW"))
            if abs(c.eb2) > 150.0:
                bad.append(("IHX energy balance", round(c.eb2, 1), "kW"))
            if abs(c.hl_gap) > 5.0:
                bad.append(("hot-leg vs bulk temperature", round(c.hl_gap, 2), "°C"))
            if bad:
                if self.eb_bad_since is None:
                    self.eb_bad_since = t
                if t - self.eb_bad_since >= 3.0:
                    out.append(Condition(self.LAYER, "PROC-ENERGY", "boiler-loop", "high",
                                         "Energy balance / redundancy violation",
                                         {"violations": [{"check": b[0], "value": b[1], "unit": b[2]} for b in bad],
                                          **c.to_dict()}, min(1.0, max(abs(c.eb1), abs(c.eb2)) / 600.0), 0.8,
                                         "Identify the inconsistent instrument; mark suspicious; use twin estimate",
                                         hold_s=4.0))
            else:
                self.eb_bad_since = None
        return out
