"""Measurement self-consistency checks (analytical redundancy) from design data.

Used by the process detector (to flag implausible measurements) and by the
twin detector (to tell "the model is wrong" from "the measurements are wrong").
All inputs are SCADA observations; parameters are design-datasheet values.
"""
from __future__ import annotations

from collections import deque

from app.digital_twin.model import TwinParams


class _Slope:
    """Least-squares slope over a sliding window of (t, x)."""

    def __init__(self, n: int):
        self.buf: deque = deque(maxlen=n)

    def push(self, t: float, x: float) -> None:
        self.buf.append((t, x))

    def slope(self) -> float:
        n = len(self.buf)
        if n < 5:
            return 0.0
        mt = sum(p[0] for p in self.buf) / n
        mx = sum(p[1] for p in self.buf) / n
        num = sum((p[0] - mt) * (p[1] - mx) for p in self.buf)
        den = sum((p[0] - mt) ** 2 for p in self.buf)
        return num / den if den > 1e-12 else 0.0

    def mean(self) -> float:
        n = len(self.buf)
        return sum(p[1] for p in self.buf) / n if n else 0.0

    @property
    def full(self) -> bool:
        return len(self.buf) == self.buf.maxlen


class BoilerConsistency:
    TAGS = ("JT-101", "TT-101", "TT-102", "TT-103", "FT-101", "TT-201", "TT-202", "FT-201")

    def __init__(self, params: TwinParams | None = None, window: int = 100):
        self.p = params or TwinParams()
        self.w = {k: _Slope(window) for k in self.TAGS}
        self.eb1 = 0.0
        self.eb2 = 0.0
        self.hl_gap = 0.0
        self.ready = False
        self._n = 0

    def push(self, t: float, obs: dict[str, tuple[float, bool]]) -> None:
        if not all(obs.get(k, (0, False))[1] for k in self.TAGS):
            return
        for k in self.TAGS:
            self.w[k].push(t, obs[k][0])
        self.ready = all(w.full for w in self.w.values())
        self._n += 1
        if not self.ready or self._n % 5:
            return
        p = self.p
        m = {k: self.w[k].mean() for k in self.TAGS}
        c_b = p.m_boiler * p.cp_lm
        c_x = p.m_ihx * p.cp_lm
        c_so = p.m_so * p.cp_w
        # boiler node: Q_heater = m cp (T_b - T_cl) + UA_loss (T_b - T_amb) + C_b dT_b/dt
        self.eb1 = (m["JT-101"] - m["FT-101"] * p.cp_lm * (m["TT-103"] - m["TT-102"])
                    - p.ua_loss * (m["TT-103"] - p.t_amb) - c_b * self.w["TT-103"].slope())
        # IHX: primary enthalpy drop (minus storage) == secondary enthalpy rise (plus storage)
        q_prim = m["FT-101"] * p.cp_lm * (m["TT-101"] - m["TT-102"]) - c_x * self.w["TT-102"].slope()
        q_sec = m["FT-201"] * p.cp_w * (m["TT-202"] - m["TT-201"]) + c_so * self.w["TT-202"].slope()
        self.eb2 = q_prim - q_sec
        # hot leg is a short transport lag of the boiler bulk temperature
        self.hl_gap = m["TT-101"] - m["TT-103"]

    def consistent(self, eb_tol: float = 150.0, gap_tol: float = 5.0) -> bool:
        return self.ready and abs(self.eb1) < eb_tol and abs(self.eb2) < eb_tol and abs(self.hl_gap) < gap_tol

    def to_dict(self) -> dict:
        return {"ready": self.ready, "boiler_balance_kw": round(self.eb1, 1), "ihx_balance_kw": round(self.eb2, 1),
                "hotleg_vs_bulk_c": round(self.hl_gap, 2), "consistent": self.consistent()}
