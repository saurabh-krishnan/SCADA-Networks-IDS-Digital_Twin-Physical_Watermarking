"""Reproducible, bounded watermark excitation.

The excitation is a piecewise-constant pseudo-random sequence.  Level ``k`` is a
pure function of (seed, k) so the PLC (which injects it) and the detector (which
predicts its effect) generate identical values without exchanging them over the
network, and any experiment can be replayed bit-for-bit.
"""
from __future__ import annotations

import math

from app.core.rng import hash_uniform


class WatermarkSignal:
    MODES = ("prbs", "uniform")

    def __init__(self, seed: int, amplitude: float, hold_s: float, mode: str = "prbs"):
        if mode not in self.MODES:
            raise ValueError(f"mode must be one of {self.MODES}")
        if amplitude < 0:
            raise ValueError("amplitude must be non-negative")
        if hold_s <= 0:
            raise ValueError("hold_s must be positive")
        self.seed = int(seed)
        self.amplitude = float(amplitude)
        self.hold_s = float(hold_s)
        self.mode = mode

    def level(self, slot: int) -> float:
        u = hash_uniform(self.seed, 0x574D, slot)
        if self.mode == "prbs":
            return self.amplitude if u >= 0.5 else -self.amplitude
        return self.amplitude * (2.0 * u - 1.0)

    def value(self, t: float, t0: float) -> float:
        if t < t0:
            return 0.0
        return self.level(int(math.floor((t - t0) / self.hold_s + 1e-9)))

    def sequence(self, n: int) -> list[float]:
        return [self.level(k) for k in range(n)]
