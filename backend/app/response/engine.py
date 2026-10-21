"""Defensive response engine (acts on simulated components only).

Modes:
* monitor    — record recommendations; change nothing.
* approval   — queue recommended actions; execute only after operator approval.
* auto       — execute recommended actions automatically.

Responses act through narrow, simulated effects (network quarantine, PLC write
allow-list, directory account disable, SCADA setpoint restore, a reduced-load
"safe" supervisory state, experiment pause, evidence snapshot). The engine is
never given the safety system: process safety remains the SIS's job.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Callable, Optional

from app.core.util import IdGen, now_iso

ACTIONS = {
    "quarantine_endpoint": "Quarantine a simulated endpoint (drop its traffic at the switch)",
    "reject_unauthorized_commands": "Enable the PLC write allow-list",
    "restore_setpoint": "Restore an operator-approved setpoint",
    "disable_user": "Disable a directory user account and revoke its sessions",
    "mark_suspicious": "Flag a device as suspicious in the asset inventory",
    "failover_secure_channel": "Switch supervisory writes to an authenticated anti-replay channel",
    "enter_safe_state": "Command a predefined reduced-load supervisory state",
    "resync_twin": "Restore twin design parameters and resynchronise",
    "preserve_evidence": "Snapshot telemetry, traffic and alerts for the incident",
    "pause_experiment": "Pause the running experiment",
}


class ResponseEngine:
    def __init__(self, hooks: dict[str, Callable[..., Any]]):
        self.mode = "monitor"  # monitor | approval | auto
        self.hooks = hooks
        self.pending: dict[str, dict] = {}
        self.history: deque[dict] = deque(maxlen=500)
        self._id = IdGen("RSP")
        self.applied_effects: list[dict] = []

    def set_mode(self, mode: str) -> None:
        if mode not in ("monitor", "approval", "auto"):
            raise ValueError("mode must be monitor|approval|auto")
        self.mode = mode

    # ------------------------------------------------------------------ intake
    def handle_incident(self, t: float, incident) -> list[dict]:
        created = []
        # Dedup only against actioned items (pending approval / executed) so that switching
        # from monitor to approval/auto re-offers previously "recommended" items.
        existing = {(r["action"], r["target"]) for r in self.history
                    if r.get("incident_id") == incident.id and r.get("status") in ("executed", "failed", "rejected")} | {
            (r["action"], r["target"]) for r in self.pending.values() if r.get("incident_id") == incident.id}
        recommended = {(r["action"], r["target"]) for r in self.history
                       if r.get("incident_id") == incident.id and r.get("status") == "recommended"}
        for rec in incident.recommendations:
            key = (rec["action"], rec["target"])
            if key in existing or (self.mode == "monitor" and key in recommended):
                continue
            item = {"id": self._id(), "t": round(t, 2), "wall_time": now_iso(), "incident_id": incident.id,
                    "action": rec["action"], "target": rec["target"], "reason": rec["reason"],
                    "description": ACTIONS.get(rec["action"], rec["action"]), "mode": self.mode}
            if self.mode == "monitor":
                item["status"] = "recommended"
                self.history.append(item)
            elif self.mode == "approval":
                item["status"] = "pending_approval"
                self.pending[item["id"]] = item
                incident.response_ids.append(item["id"])
            else:
                self._execute(t, item, incident)
            created.append(item)
        return created

    # ------------------------------------------------------------------ approval flow
    def approve(self, t: float, response_id: str, operator: str, incident_lookup) -> dict:
        item = self.pending.pop(response_id, None)
        if item is None:
            return {"ok": False, "error": "no such pending response"}
        item["approved_by"] = operator
        inc = incident_lookup(item["incident_id"])
        self._execute(t, item, inc)
        return {"ok": True, "response": item}

    def reject(self, t: float, response_id: str, operator: str) -> dict:
        item = self.pending.pop(response_id, None)
        if item is None:
            return {"ok": False, "error": "no such pending response"}
        item.update(status="rejected", rejected_by=operator, t_done=round(t, 2))
        self.history.append(item)
        return {"ok": True, "response": item}

    # ------------------------------------------------------------------ execution
    def _execute(self, t: float, item: dict, incident) -> None:
        hook = self.hooks.get(item["action"])
        try:
            effect = hook(t, item["target"], incident) if hook else {"note": "no handler"}
            item.update(status="executed", t_done=round(t, 2), effect=effect)
        except Exception as exc:  # pragma: no cover - defensive
            item.update(status="failed", t_done=round(t, 2), error=str(exc))
        self.history.append(item)
        self.applied_effects.append({"t": round(t, 2), "action": item["action"], "target": item["target"],
                                     "incident_id": item.get("incident_id")})
        if incident is not None and item["id"] not in incident.response_ids:
            incident.response_ids.append(item["id"])
        if incident is not None and item.get("status") == "executed":
            incident.status = "responding"
            incident.timeline.append({"t": round(t, 2), "event": f"response executed: {item['action']} "
                                                                  f"→ {item['target']}", "response": item["id"]})

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "actions": ACTIONS,
            "pending": list(self.pending.values()),
            "history": list(self.history)[-60:][::-1],
            "applied_effects": self.applied_effects[-40:],
        }
