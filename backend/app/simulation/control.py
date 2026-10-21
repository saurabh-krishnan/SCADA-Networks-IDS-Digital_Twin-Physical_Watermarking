from __future__ import annotations

from app.core.util import clamp


class PID:
    """Positional PI(D) controller with conditional-integration anti-windup.

    ``direct=False`` (reverse acting): output rises when PV is below SP (heater).
    ``direct=True``  (direct acting):  output rises when PV is above SP (cooling fan).
    """

    def __init__(self, kp: float, ti: float, td: float = 0.0, lo: float = 0.0, hi: float = 100.0,
                 direct: bool = False):
        self.kp, self.ti, self.td = kp, ti, td
        self.lo, self.hi = lo, hi
        self.direct = direct
        self.i = 0.0
        self.prev_pv: float | None = None
        self.out = lo

    def error(self, sp: float, pv: float) -> float:
        return (pv - sp) if self.direct else (sp - pv)

    def init_output(self, out: float) -> None:
        """Bumpless start: integral state chosen so output == ``out`` at zero error."""
        self.i = clamp(out, self.lo, self.hi)
        self.out = self.i

    def update(self, sp: float, pv: float, dt: float) -> float:
        e = self.error(sp, pv)
        p = self.kp * e
        d = 0.0
        if self.td > 0 and self.prev_pv is not None and dt > 0:
            dpv = (pv - self.prev_pv) / dt
            d = -self.kp * self.td * (dpv if not self.direct else -dpv)
        self.prev_pv = pv
        i_new = self.i + (self.kp * dt / self.ti * e if self.ti > 0 else 0.0)
        out = p + i_new + d
        if (out > self.hi and e > 0) or (out < self.lo and e < 0):
            out = p + self.i + d  # stop integrating into saturation
        else:
            self.i = clamp(i_new, self.lo - abs(p), self.hi + abs(p))
        self.out = clamp(out, self.lo, self.hi)
        return self.out
