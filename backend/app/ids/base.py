"""Common IDS data model: conditions -> findings (deduplicated alert records).

A detector reports *conditions* (rule currently true for an asset, with
evidence).  The ``FindingManager`` turns them into alert records:
* the first report of (layer, rule, asset) raises a new finding,
* repeated reports update the same finding (count, last-seen, evidence, peak
  score) instead of creating duplicates,
* a finding clears once it has not been re-reported for its hold time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.core.util import IdGen, now_iso, sev_max

LAYERS = ("network", "process", "twin", "watermark")


@dataclass
class Condition:
    layer: str
    rule: str
    asset: str
    severity: str
    category: str
    evidence: dict
    score: Optional[float] = None
    confidence: float = 0.6
    recommendation: str = ""
    hold_s: float = 5.0  # how long the finding stays active after the last report


@dataclass
class Finding:
    id: str
    layer: str
    rule: str
    asset: str
    severity: str
    category: str
    evidence: dict
    score: Optional[float]
    confidence: float
    recommendation: str
    t_first: float
    t_last: float
    wall_time: str
    hold_s: float
    count: int = 1
    active: bool = True
    cleared_at: Optional[float] = None
    status: str = "open"  # open | acknowledged | responding | resolved
    incident_id: Optional[str] = None
    peak_score: Optional[float] = None
    timeline: list = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.layer, self.rule, self.asset)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "timestamp": round(self.t_first, 2), "last_seen": round(self.t_last, 2),
            "wall_time": self.wall_time, "asset": self.asset, "severity": self.severity, "category": self.category,
            "source": self.layer, "rule": self.rule, "evidence": self.evidence,
            "score": None if self.score is None else round(self.score, 4),
            "peak_score": None if self.peak_score is None else round(self.peak_score, 4),
            "confidence": round(self.confidence, 3), "recommendation": self.recommendation,
            "status": self.status, "active": self.active,
            "cleared_at": None if self.cleared_at is None else round(self.cleared_at, 2),
            "count": self.count, "incident_id": self.incident_id,
        }


class FindingManager:
    def __init__(self) -> None:
        self.active: dict[tuple[str, str, str], Finding] = {}
        self.all: list[Finding] = []
        self.by_id: dict[str, Finding] = {}
        self._id = IdGen("ALR")
        self.new_events: list[tuple[str, Finding]] = []  # ("raised"|"updated"|"cleared", finding)

    def report(self, t: float, c: Condition) -> Finding:
        key = (c.layer, c.rule, c.asset)
        f = self.active.get(key)
        if f is None:
            f = Finding(self._id(), c.layer, c.rule, c.asset, c.severity, c.category, c.evidence, c.score,
                        c.confidence, c.recommendation, t, t, now_iso(), c.hold_s, peak_score=c.score)
            self.active[key] = f
            self.all.append(f)
            self.by_id[f.id] = f
            self.new_events.append(("raised", f))
        else:
            f.t_last = t
            f.count += 1
            f.evidence = c.evidence
            f.score = c.score
            f.hold_s = c.hold_s
            if c.score is not None:
                f.peak_score = c.score if f.peak_score is None else max(f.peak_score, c.score)
            if sev_max(f.severity, c.severity) != f.severity:
                f.severity = c.severity
                self.new_events.append(("updated", f))
            f.confidence = max(f.confidence, c.confidence)
        return f

    def sweep(self, t: float) -> None:
        for key, f in list(self.active.items()):
            if t - f.t_last > f.hold_s:
                f.active = False
                f.cleared_at = t
                if f.status in ("open", "acknowledged", "responding"):
                    f.status = "resolved"
                del self.active[key]
                self.new_events.append(("cleared", f))

    def drain(self) -> list[tuple[str, Finding]]:
        ev, self.new_events = self.new_events, []
        return ev

    def active_layers(self) -> set[str]:
        return {f.layer for f in self.active.values() if f.severity != "info"}
