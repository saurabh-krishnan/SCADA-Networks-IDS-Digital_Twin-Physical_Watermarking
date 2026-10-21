"""Watermark response evaluation.

For each measurement channel we keep, over a sliding window,
  e[k] = expected watermark response (high-passed)   — from the twin's shadow models
  o[k] = observed response (high-passed measurement) — from SCADA telemetry
and compute
  rho   = Pearson correlation(e, o)
  beta  = <o, e> / <e, e>          (response gain; calibrated baseline beta0)
  snr   = std(beta0 e) / std(o - beta0 e)
Decision per channel (after baseline calibration):
  consistent   rho >= rho_ok and beta/beta0 in [gain_lo_ok, gain_hi_ok]
  suspicious   rho <  rho_bad                       (missing / uncorrelated response)
               or beta/beta0 outside [gain_lo_bad, gain_hi_bad] (excessive response error)
  inconclusive otherwise, or when data, SNR or measurement quality are insufficient.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass
class DecisionThresholds:
    rho_ok: float = 0.5
    rho_bad: float = 0.25
    gain_lo_ok: float = 0.6
    gain_hi_ok: float = 1.5
    gain_lo_bad: float = 0.35
    gain_hi_bad: float = 2.2
    min_valid_frac: float = 0.8
    min_snr: float = 0.6


def _stats(e: list[float], o: list[float]) -> tuple[float, float, float, float]:
    n = len(e)
    me = sum(e) / n
    mo = sum(o) / n
    see = soo = seo = 0.0
    for a, b in zip(e, o):
        da, db = a - me, b - mo
        see += da * da
        soo += db * db
        seo += da * db
    rho = seo / math.sqrt(see * soo) if see > 1e-18 and soo > 1e-18 else 0.0
    beta = seo / see if see > 1e-18 else 0.0
    return rho, beta, math.sqrt(see / n), math.sqrt(soo / n)


class ChannelEvaluator:
    def __init__(self, name: str, window: int):
        self.name = name
        self.window = window
        self.e: deque = deque(maxlen=window)
        self.o: deque = deque(maxlen=window)
        self.valid: deque = deque(maxlen=window)
        self.beta0: float | None = None
        self.rho0: float | None = None
        self._cal_betas: list[float] = []
        self._cal_rhos: list[float] = []
        self.last: dict = {}

    def push(self, e: float, o: float, valid: bool) -> None:
        self.e.append(e)
        self.o.append(o)
        self.valid.append(valid)

    def reset(self, keep_calibration: bool = False) -> None:
        self.e.clear()
        self.o.clear()
        self.valid.clear()
        if not keep_calibration:
            self.beta0 = self.rho0 = None
            self._cal_betas, self._cal_rhos = [], []

    def evaluate(self, th: DecisionThresholds, calibrating: bool) -> dict:
        n = len(self.valid)
        nv = sum(1 for v in self.valid if v)
        res = {"channel": self.name, "n": n, "valid_frac": round(nv / self.window, 3) if self.window else 0.0}
        if n < self.window or nv < th.min_valid_frac * self.window:
            res.update(decision="inconclusive", reason="insufficient valid samples in window")
            self.last = res
            return res
        e = [x for x, v in zip(self.e, self.valid) if v]
        o = [x for x, v in zip(self.o, self.valid) if v]
        rho, beta, se, so = _stats(e, o)
        res.update(rho=round(rho, 4), beta=round(beta, 4), std_expected=round(se, 5), std_observed=round(so, 5))
        if calibrating:
            self._cal_betas.append(beta)
            self._cal_rhos.append(rho)
            res.update(decision="inconclusive", reason="baseline calibration")
            self.last = res
            return res
        if self.beta0 is None:
            if not self._cal_betas:
                res.update(decision="inconclusive", reason="no baseline")
                self.last = res
                return res
            self.beta0 = sorted(self._cal_betas)[len(self._cal_betas) // 2]
            self.rho0 = sorted(self._cal_rhos)[len(self._cal_rhos) // 2]
        b0 = self.beta0
        res.update(beta0=round(b0, 4), rho0=round(self.rho0 or 0.0, 4))
        if b0 <= 1e-6 or (self.rho0 or 0.0) < th.rho_ok:
            res.update(decision="inconclusive", reason="watermark not observable in baseline (low SNR)")
            self.last = res
            return res
        gain = beta / b0
        resid = math.sqrt(max(0.0, so * so - 2 * b0 * beta * se * se + b0 * b0 * se * se))
        snr = (b0 * se) / resid if resid > 1e-12 else 99.0
        res.update(gain_ratio=round(gain, 4), snr=round(snr, 3),
                   response_error=round(resid / (b0 * se), 4) if se > 0 else None)
        if se * b0 < 1e-9:
            res.update(decision="inconclusive", reason="expected response too small")
        elif rho < th.rho_bad:
            kind = "missing expected response" if abs(gain) < th.gain_lo_bad else "abnormal correlation"
            res.update(decision="suspicious", reason=kind)
        elif not (th.gain_lo_bad <= gain <= th.gain_hi_bad):
            res.update(decision="suspicious", reason="excessive response error")
        elif snr < th.min_snr and rho < th.rho_ok:
            res.update(decision="inconclusive", reason="measurement noise too high for a decision")
        elif rho >= th.rho_ok and th.gain_lo_ok <= gain <= th.gain_hi_ok:
            res.update(decision="consistent", reason="observed response matches watermark")
        else:
            res.update(decision="inconclusive", reason="grey zone between thresholds")
        self.last = res
        return res
