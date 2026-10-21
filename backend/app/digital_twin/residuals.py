"""Residual analysis: residual = observed - predicted.

For every monitored variable we track
* raw residual and normalised deviation z = (r - bias) / sigma,
* a two-sided CUSUM (persistence),
* a sudden-error counter (consecutive |z| above a large threshold),
* an anomaly score in [0, 1] = CUSUM / threshold (configurable k, h).

``sigma`` combines sensor noise and model error.  During a calibration window
(after start-up or a resync) the tracker estimates the residual bias and spread
and widens sigma if the model turns out to be worse than configured (capped).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass
class ResidualConfig:
    cusum_k: float = 1.5  # allowance (in sigma)
    cusum_h: float = 30.0  # decision threshold
    sudden_z: float = 8.0
    sudden_n: int = 3
    calib_s: float = 40.0
    sigma_cap: float = 3.0


class ResidualTracker:
    def __init__(self, tag: str, sigma: float, cfg: ResidualConfig, history: int = 600):
        self.tag = tag
        self.sigma_cfg = sigma
        self.sigma = sigma
        self.cfg = cfg
        self.bias = 0.0
        self.r = 0.0
        self.z = 0.0
        self.s_pos = 0.0
        self.s_neg = 0.0
        self.sudden_count = 0
        self.alarm_since: float | None = None
        self.calibrating = True
        self._cal: list[float] = []
        self._cal_t0: float | None = None
        self.hist: deque = deque(maxlen=history)  # (t, obs, pred, r, z)
        self.pred = float("nan")
        self.obs = float("nan")
        self.valid = False

    def reset(self, keep_calibration: bool = True) -> None:
        self.s_pos = self.s_neg = 0.0
        self.sudden_count = 0
        self.alarm_since = None
        if not keep_calibration:
            self.calibrating = True
            self._cal = []
            self._cal_t0 = None
            self.bias = 0.0
            self.sigma = self.sigma_cfg

    @property
    def score(self) -> float:
        return min(1.0, max(self.s_pos, self.s_neg) / self.cfg.cusum_h)

    @property
    def cusum(self) -> float:
        return max(self.s_pos, self.s_neg)

    @property
    def persistent(self) -> bool:
        return self.cusum >= self.cfg.cusum_h

    @property
    def sudden(self) -> bool:
        return self.sudden_count >= self.cfg.sudden_n

    def update(self, t: float, obs: float, pred: float, valid: bool) -> None:
        self.pred = pred
        self.obs = obs
        self.valid = valid
        if not valid or obs != obs:
            self.hist.append((t, None, pred, None, None))
            return
        r = obs - pred
        self.r = r
        if self.calibrating:
            if self._cal_t0 is None:
                self._cal_t0 = t
            self._cal.append(r)
            if t - self._cal_t0 >= self.cfg.calib_s and len(self._cal) >= 20:
                n = len(self._cal)
                m = sum(self._cal) / n
                sd = math.sqrt(sum((x - m) ** 2 for x in self._cal) / (n - 1))
                self.bias = m
                self.sigma = min(self.sigma_cfg * self.cfg.sigma_cap, max(self.sigma_cfg, 1.1 * sd))
                self.calibrating = False
        z = (r - self.bias) / self.sigma
        self.z = z
        if not self.calibrating:
            k = self.cfg.cusum_k
            self.s_pos = min(5 * self.cfg.cusum_h, max(0.0, self.s_pos + z - k))
            self.s_neg = min(5 * self.cfg.cusum_h, max(0.0, self.s_neg - z - k))
            self.sudden_count = self.sudden_count + 1 if abs(z) >= self.cfg.sudden_z else 0
            if self.persistent or self.sudden:
                if self.alarm_since is None:
                    self.alarm_since = t
            elif self.cusum < 0.3 * self.cfg.cusum_h:
                self.alarm_since = None
        self.hist.append((t, obs, pred, r, z))

    def to_dict(self) -> dict:
        def f(x):
            return None if x is None or x != x else round(x, 4)
        return {
            "tag": self.tag, "observed": f(self.obs), "predicted": f(self.pred), "residual": f(self.r),
            "z": f(self.z), "sigma": f(self.sigma), "bias": f(self.bias), "cusum": f(self.cusum),
            "score": f(self.score), "persistent": self.persistent, "sudden": self.sudden,
            "alarm_since": self.alarm_since, "calibrating": self.calibrating, "valid": self.valid,
        }
