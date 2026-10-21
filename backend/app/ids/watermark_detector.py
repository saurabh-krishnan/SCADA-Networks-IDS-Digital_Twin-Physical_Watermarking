"""Watermark layer: turns watermark-engine decisions into IDS conditions."""
from __future__ import annotations

from app.ids.base import Condition
from app.watermarking.engine import WatermarkEngine


class WatermarkDetector:
    LAYER = "watermark"

    def __init__(self, engine: WatermarkEngine):
        self.engine = engine
        self._inconclusive_since: float | None = None

    def evaluate(self, t: float) -> list[Condition]:
        wm = self.engine
        out: list[Condition] = []
        if not wm.enabled or not wm.decisions:
            self._inconclusive_since = None
            return out
        last = wm.decisions[-1]
        ev = {"decision": last["decision"], "reason": last["reason"], "streak": last["streak"],
              "channels": {k: {kk: v.get(kk) for kk in ("rho", "gain_ratio", "snr", "valid_frac", "reason")}
                           for k, v in last["channels"].items()},
              "amplitude_pct": wm.cfg.amplitude, "target": wm.cfg.target, "seed": wm.cfg.seed}
        if wm.alarm:
            reason = last["reason"]
            cat = ("Missing expected watermark response" if "missing" in reason else
                   "Excessive watermark response error" if "excessive" in reason else
                   "Abnormal watermark correlation")
            rhos = [c.get("rho") for c in last["channels"].values() if c.get("rho") is not None]
            score = 1.0 - max(0.0, min(rhos)) if rhos else 1.0
            out.append(Condition(self.LAYER, "WM-SUSPICIOUS", "P-101/FT-101", "high", cat, ev, score, 0.85,
                                 "Telemetry may be replayed or manipulated: fail over to secure channel, "
                                 "verify with independent instruments", hold_s=3.0))
        if last["decision"] == "inconclusive" and wm.calibrated_at is not None:
            if self._inconclusive_since is None:
                self._inconclusive_since = t
            if t - self._inconclusive_since > 20.0:
                out.append(Condition(self.LAYER, "WM-INCONCLUSIVE", "P-101/FT-101", "info",
                                     "Watermark verification unavailable", ev, None, 0.3,
                                     "Check measurement quality / suspension reason", hold_s=3.0))
        else:
            self._inconclusive_since = None
        return out
