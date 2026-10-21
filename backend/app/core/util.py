from __future__ import annotations

import datetime as _dt
import itertools
import math
from collections import deque
from typing import Iterable

SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


def sev_rank(sev: str) -> int:
    return SEVERITY_ORDER.index(sev) if sev in SEVERITY_ORDER else 0


def sev_max(*sevs: str) -> str:
    return max(sevs, key=sev_rank) if sevs else "info"


def sev_bump(sev: str, levels: int) -> str:
    return SEVERITY_ORDER[min(len(SEVERITY_ORDER) - 1, sev_rank(sev) + levels)]


def r(x: float | None, nd: int = 3) -> float | None:
    """Round for JSON transport; NaN/inf become None."""
    if x is None:
        return None
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return round(float(x), nd)


class IdGen:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self._c = itertools.count(1)

    def __call__(self) -> str:
        return f"{self.prefix}-{next(self._c):05d}"


class RollingStats:
    """Fixed-length window with O(1) mean/variance updates."""

    __slots__ = ("n", "buf", "s", "s2")

    def __init__(self, n: int):
        self.n = n
        self.buf: deque[float] = deque(maxlen=n)
        self.s = 0.0
        self.s2 = 0.0

    def push(self, x: float) -> None:
        if len(self.buf) == self.n:
            old = self.buf[0]
            self.s -= old
            self.s2 -= old * old
        self.buf.append(x)
        self.s += x
        self.s2 += x * x

    @property
    def full(self) -> bool:
        return len(self.buf) == self.n

    @property
    def mean(self) -> float:
        return self.s / len(self.buf) if self.buf else 0.0

    @property
    def var(self) -> float:
        k = len(self.buf)
        if k < 2:
            return 0.0
        m = self.s / k
        return max(0.0, self.s2 / k - m * m)

    @property
    def std(self) -> float:
        return math.sqrt(self.var)

    def all_equal(self) -> bool:
        if not self.buf:
            return False
        first = self.buf[0]
        return all(v == first for v in self.buf)

    def clear(self) -> None:
        self.buf.clear()
        self.s = 0.0
        self.s2 = 0.0


def mean(xs: Iterable[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0
