"""Correlation engine: merges findings from all layers into incident records.

* Findings join an open incident in the same zone updated within the
  correlation window; otherwise they open a new incident.
* Duplicate findings never double-count: confidence combines the *best* finding
  per layer, 1 - prod(1 - c_layer); severity is the worst finding, raised one
  level per additional corroborating layer.
* The incident's classification is a transparent rule over which rules fired.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.core.util import IdGen, now_iso, sev_bump, sev_max, sev_rank
from app.ids.base import Finding

ZONE = {
    "PLC-1": "boiler", "PLC-2": "boiler", "boiler-loop": "boiler", "P-101/FT-101": "boiler", "TWIN-01": "boiler",
    "PLC-3": "water", "PLC-4": "mixing", "RTU-5": "pipeline",
}
PREFIX_ZONE = {"1": "boiler", "2": "boiler", "3": "water", "4": "mixing", "5": "pipeline"}


def zone_of(f: Finding) -> str:
    for cand in (f.asset, f.evidence.get("dst"), f.evidence.get("plc"), f.evidence.get("tag")):
        if not cand:
            continue
        if cand in ZONE:
            return ZONE[cand]
        tail = cand.split("-")[-1]
        if tail[:1] in PREFIX_ZONE and tail[:1].isdigit() and len(tail) == 3:
            return PREFIX_ZONE[tail[:1]]
    return "network"


@dataclass
class Incident:
    id: str
    created: float
    updated: float
    wall_time: str
    zone: str
    status: str = "open"
    severity: str = "low"
    classification: str = "Anomaly (unclassified)"
    confidence: float = 0.0
    assets: set = field(default_factory=set)
    layers: set = field(default_factory=set)
    rules: set = field(default_factory=set)
    finding_ids: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    response_ids: list = field(default_factory=list)
    resolved_at: Optional[float] = None
    acknowledged: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id, "created": round(self.created, 2), "updated": round(self.updated, 2),
            "wall_time": self.wall_time, "zone": self.zone, "status": self.status, "severity": self.severity,
            "classification": self.classification, "confidence": round(self.confidence, 3),
            "assets": sorted(self.assets), "layers": sorted(self.layers), "rules": sorted(self.rules),
            "alert_ids": list(self.finding_ids), "timeline": self.timeline[-60:],
            "recommendations": self.recommendations, "response_ids": list(self.response_ids),
            "resolved_at": self.resolved_at, "acknowledged": self.acknowledged,
        }


def classify(rules: set[str], findings: list[Finding]) -> str:
    falsification = any(r in rules for r in ("TWIN-SUDDEN", "PROC-ENERGY", "PROC-ROC", "WM-SUSPICIOUS", "PROC-FROZEN")) \
        or any(f.rule == "TWIN-CORRELATED" and not f.evidence.get("measurements_self_consistent") for f in findings)
    dos = any(r in rules for r in ("NET-FLOOD", "NET-COMM-DEGRADED", "NET-RATE"))
    unauth = any(r in rules for r in ("NET-UNAUTH-WRITE", "NET-WRITE-VALUE")) or (
        "PROC-SP-MISMATCH" in rules and "NET-UNKNOWN-DEVICE" in rules)
    if (dos or unauth) and falsification and len({f.layer for f in findings}) >= 3:
        return "Coordinated process and network attack"
    if "NET-REPLAY" in rules:
        return "Command replay"
    if unauth:
        return "Unauthorized setpoint modification"
    if "NET-POLICY-WRITE" in rules or "NET-AUTH-ANOMALY" in rules:
        return "Insider misuse"
    if dos:
        return "Denial of service"
    if "NET-TWIN-CONFIG" in rules:
        return "Digital-twin model tampering"
    if "PROC-FROZEN" in rules:
        return "Frozen sensor / stale telemetry"
    if "WM-SUSPICIOUS" in rules:
        return "Telemetry replay / watermark interference"
    if "PROC-SP-MISMATCH" in rules:
        return "Unauthorized setpoint modification"
    if ("PROC-PUMP-FLOW" in rules or "PROC-ACT-FB" in rules) and "PROC-ENERGY" not in rules:
        return "Actuator manipulation"
    if any(f.rule == "TWIN-CORRELATED" and f.evidence.get("measurements_self_consistent") for f in findings):
        return "Model mismatch / unmodelled process change"
    if falsification or "TWIN-PERSIST" in rules:
        return "False data injection (suspected)"
    if "NET-MAC-MISMATCH" in rules or "NET-ARP-SPOOF" in rules:
        return "Man-in-the-middle preparation"
    if "NET-UNKNOWN-DEVICE" in rules or "NET-UNEXPECTED-FLOW" in rules:
        return "Unexpected network activity"
    if rules <= {"PROC-LIMIT"}:
        return "Process upset"
    return "Anomaly (unclassified)"


def recommend(cls: str, findings: list[Finding]) -> list[dict]:
    ev_src = [f.evidence.get("src") for f in findings if f.layer == "network" and f.evidence.get("src")]
    unknown_src = [f.asset for f in findings if f.rule == "NET-UNKNOWN-DEVICE"]
    spoofers = [f.evidence.get("observed_mac") for f in findings if f.rule == "NET-MAC-MISMATCH"]
    registers = sorted({f.evidence.get("register") for f in findings if f.rule == "PROC-SP-MISMATCH"} |
                       {w["register"] for f in findings if f.rule in ("NET-UNAUTH-WRITE", "NET-POLICY-WRITE",
                                                                      "NET-REPLAY")
                        for w in f.evidence.get("writes", []) if w.get("register") != "HEARTBEAT"})
    users = sorted({f.evidence.get("session_user") or f.evidence.get("user") for f in findings
                    if f.rule in ("NET-POLICY-WRITE", "NET-AUTH-ANOMALY")} - {None})
    sensors = sorted({f.asset for f in findings if f.layer in ("twin", "process") and f.asset[:2] in ("TT", "FT", "PT")})
    plcs = sorted({f.evidence.get("dst") or f.asset for f in findings if (f.evidence.get("dst") or f.asset or "")
                   .startswith("PLC")}) or ["PLC-1"]
    recs: list[dict] = []

    def add(action: str, target: str, reason: str) -> None:
        if not any(r["action"] == action and r["target"] == target for r in recs):
            recs.append({"action": action, "target": target, "reason": reason})

    quarantine = sorted(set(unknown_src)) or ([f"mac:{spoofers[0]}"] if spoofers else [])
    if cls in ("Unauthorized setpoint modification", "Command replay", "Coordinated process and network attack"):
        for p in plcs:
            add("reject_unauthorized_commands", p, "enforce PLC write allow-list")
        for q in quarantine:
            add("quarantine_endpoint", q, "isolate the source of unauthorised traffic")
        for r in registers:
            add("restore_setpoint", r, "return register to the operator-approved value")
    if cls in ("Command replay",):
        add("failover_secure_channel", plcs[0], "authenticated channel with anti-replay protection")
    if cls == "Insider misuse":
        for u in users:
            add("disable_user", u, "revoke the account used for out-of-policy writes")
        for r in registers:
            add("restore_setpoint", r, "return register to the operator-approved value")
    if cls == "Denial of service":
        for q in quarantine:
            add("quarantine_endpoint", q, "isolate flooding source")
        add("failover_secure_channel", plcs[0], "move supervisory polling to the redundant channel")
    if cls in ("False data injection (suspected)", "Frozen sensor / stale telemetry",
               "Telemetry replay / watermark interference", "Coordinated process and network attack"):
        for s in sensors[:4] or ["FT-101"]:
            add("mark_suspicious", s, "telemetry contradicts physics / watermark")
        add("failover_secure_channel", "PLC-1", "bypass a possible man-in-the-middle on the telemetry path")
    if cls == "Actuator manipulation":
        for f in findings:
            if f.rule in ("PROC-PUMP-FLOW", "PROC-ACT-FB"):
                add("mark_suspicious", f.asset, "actuator does not respond as commanded")
        add("enter_safe_state", "boiler", "reduce thermal load while the actuator is untrusted")
    if cls in ("Digital-twin model tampering", "Model mismatch / unmodelled process change"):
        add("resync_twin", "TWIN-01", "restore design parameters and resynchronise the twin")
    if cls == "Coordinated process and network attack":
        add("enter_safe_state", "boiler", "multiple layers indicate an active attack")
    if cls not in ("Process upset",):
        add("preserve_evidence", "incident", "snapshot telemetry, traffic and alerts")
    return recs


class CorrelationEngine:
    WINDOW_S = 60.0
    RESOLVE_AFTER_S = 30.0

    def __init__(self) -> None:
        self.incidents: dict[str, Incident] = {}
        self._id = IdGen("INC")
        self.changed: set[str] = set()

    def ingest(self, t: float, events: list[tuple[str, Finding]], findings_by_id: dict[str, Finding]) -> None:
        for kind, f in events:
            if f.severity == "info":
                continue
            if kind == "raised":
                inc = self._match(t, f)
                if inc is None:
                    inc = Incident(self._id(), t, t, now_iso(), zone_of(f))
                    self.incidents[inc.id] = inc
                    inc.timeline.append({"t": round(t, 2), "event": "incident opened", "by": f.id})
                f.incident_id = inc.id
                inc.finding_ids.append(f.id)
                inc.timeline.append({"t": round(t, 2), "event": f"{f.layer}: {f.category}", "alert": f.id,
                                     "asset": f.asset, "severity": f.severity})
                if inc.status == "resolved":
                    inc.status = "open"
                    inc.resolved_at = None
                    inc.timeline.append({"t": round(t, 2), "event": "incident re-opened"})
                inc.updated = t
                self._recompute(inc, findings_by_id)
            elif kind == "cleared" and f.incident_id in self.incidents:
                inc = self.incidents[f.incident_id]
                inc.timeline.append({"t": round(t, 2), "event": f"cleared: {f.category}", "alert": f.id})
                self.changed.add(inc.id)
            elif kind == "updated" and f.incident_id in self.incidents:
                self._recompute(self.incidents[f.incident_id], findings_by_id)
        for inc in self.incidents.values():
            if inc.status == "resolved":
                continue
            fs = [findings_by_id[i] for i in inc.finding_ids]
            if all(not x.active for x in fs):
                last = max((x.cleared_at or x.t_last) for x in fs)
                if t - last >= self.RESOLVE_AFTER_S:
                    inc.status = "resolved"
                    inc.resolved_at = round(t, 2)
                    inc.timeline.append({"t": round(t, 2), "event": "incident resolved (no active evidence)"})
                    self.changed.add(inc.id)
            elif any(x.active for x in fs):
                inc.updated = max(inc.updated, max(x.t_last for x in fs if x.active))

    def _match(self, t: float, f: Finding) -> Optional[Incident]:
        z = zone_of(f)
        best = None
        for inc in self.incidents.values():
            if inc.status == "resolved" and t - (inc.resolved_at or 0) > 5:
                continue
            if t - inc.updated > self.WINDOW_S:
                continue
            if inc.zone == z or f.asset in inc.assets or (f.layer == "network" and inc.zone == "network"):
                if best is None or inc.updated > best.updated:
                    best = inc
        return best

    def _recompute(self, inc: Incident, findings_by_id: dict[str, Finding]) -> None:
        fs = [findings_by_id[i] for i in inc.finding_ids]
        inc.assets = {f.asset for f in fs}
        inc.layers = {f.layer for f in fs}
        inc.rules = {f.rule for f in fs}
        best: dict[str, float] = {}
        worst = "info"
        for f in fs:
            best[f.layer] = max(best.get(f.layer, 0.0), f.confidence)
            worst = sev_max(worst, f.severity)
        conf = 1.0
        for c in best.values():
            conf *= (1.0 - c)
        inc.confidence = 1.0 - conf
        sev = sev_bump(worst, max(0, len(inc.layers) - 1))
        if sev_rank(sev) > sev_rank(inc.severity):
            inc.timeline.append({"t": round(inc.updated, 2), "event": f"severity → {sev}"})
        inc.severity = sev_max(inc.severity, sev)
        cls = classify(inc.rules, fs)
        if cls != inc.classification:
            inc.timeline.append({"t": round(inc.updated, 2), "event": f"classified: {cls}"})
            inc.classification = cls
        recs = recommend(cls, fs)
        known = {(r["action"], r["target"]) for r in inc.recommendations}
        for r in recs:
            if (r["action"], r["target"]) not in known:
                inc.recommendations.append(r)
        self.changed.add(inc.id)

    def drain_changed(self) -> list[Incident]:
        ids, self.changed = self.changed, set()
        return [self.incidents[i] for i in ids if i in self.incidents]
