"""Deterministic random-number utilities.

Every stochastic component draws from its own named stream so that, for a given
master seed, adding or removing one component (for example an attacker that
injects extra packets) does not shift the random sequence seen by the others.
This keeps normal and attack runs comparable sample-by-sample.
"""
from __future__ import annotations

import zlib

import numpy as np

MASK64 = (1 << 64) - 1


def stable_id(name: str) -> int:
    """Process-independent string hash (Python's ``hash`` is salted per run)."""
    return zlib.crc32(name.encode("utf-8"))


def splitmix64(x: int) -> int:
    x = (x + 0x9E3779B97F4A7C15) & MASK64
    z = x
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return z ^ (z >> 31)


def hash_uniform(*keys: int) -> float:
    """Counter-based uniform sample in [0, 1) derived only from ``keys``."""
    h = 0x1234_5678
    for k in keys:
        h = splitmix64(h ^ (k & MASK64))
    return (h >> 11) / float(1 << 53)


class SeedBank:
    """Factory for independent, named NumPy generators derived from one seed."""

    def __init__(self, seed: int):
        self.seed = int(seed)

    def rng(self, name: str) -> np.random.Generator:
        return np.random.default_rng([self.seed, stable_id(name)])

    def noise(self, name: str, block: int = 2048) -> "NoiseStream":
        return NoiseStream(self.rng(name), block)


class NoiseStream:
    """Buffered standard-normal stream (much faster than per-call rng.normal)."""

    __slots__ = ("_rng", "_block", "_buf", "_i")

    def __init__(self, rng: np.random.Generator, block: int = 2048):
        self._rng = rng
        self._block = block
        self._buf = rng.standard_normal(block).tolist()
        self._i = 0

    def next(self) -> float:
        if self._i >= self._block:
            self._buf = self._rng.standard_normal(self._block).tolist()
            self._i = 0
        v = self._buf[self._i]
        self._i += 1
        return v

    def uniform(self) -> float:
        return float(self._rng.random())
