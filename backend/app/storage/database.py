"""SQLite persistence for alerts, incidents, events, responses and experiments.

A single connection guarded by a lock (the simulation runs in one worker task;
the API reads on the event loop). WAL mode keeps readers from blocking the
writer. All timestamps are stored both as simulation seconds and ISO wall time.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, sim_t REAL, wall TEXT,
    category TEXT, source TEXT, severity TEXT, message TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT, run_id TEXT, sim_t REAL, last_seen REAL, wall TEXT, asset TEXT, severity TEXT,
    category TEXT, source TEXT, rule TEXT, score REAL, confidence REAL, status TEXT, incident_id TEXT,
    evidence TEXT, PRIMARY KEY (run_id, alert_id));
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT, run_id TEXT, created REAL, updated REAL, wall TEXT, zone TEXT, severity TEXT,
    classification TEXT, confidence REAL, status TEXT, data TEXT, PRIMARY KEY (run_id, incident_id));
CREATE TABLE IF NOT EXISTS responses (
    id TEXT, run_id TEXT, sim_t REAL, wall TEXT, incident_id TEXT, action TEXT, target TEXT, mode TEXT,
    status TEXT, data TEXT, PRIMARY KEY (run_id, id));
CREATE TABLE IF NOT EXISTS experiments (
    run_id TEXT PRIMARY KEY, label TEXT, created TEXT, config TEXT, metrics TEXT, status TEXT);
CREATE INDEX IF NOT EXISTS ix_events_run ON events(run_id, sim_t);
CREATE INDEX IF NOT EXISTS ix_alerts_run ON alerts(run_id, sim_t);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ------------------------------------------------------------------ writes
    def log_event(self, run_id: str, sim_t: float, wall: str, category: str, source: str, severity: str,
                  message: str, data: Optional[dict] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO events(run_id,sim_t,wall,category,source,severity,message,data) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, sim_t, wall, category, source, severity, message, json.dumps(data or {})))
            self.conn.commit()

    def upsert_alert(self, run_id: str, a: dict) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO alerts(alert_id,run_id,sim_t,last_seen,wall,asset,severity,category,source,rule,score,"
                "confidence,status,incident_id,evidence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(run_id,alert_id) DO UPDATE SET last_seen=excluded.last_seen,severity=excluded.severity,"
                "status=excluded.status,incident_id=excluded.incident_id,score=excluded.score,"
                "evidence=excluded.evidence",
                (a["id"], run_id, a["timestamp"], a["last_seen"], a["wall_time"], a["asset"], a["severity"],
                 a["category"], a["source"], a["rule"], a.get("score"), a.get("confidence"), a["status"],
                 a.get("incident_id"), json.dumps(a["evidence"])))
            self.conn.commit()

    def upsert_incident(self, run_id: str, inc: dict) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO incidents(incident_id,run_id,created,updated,wall,zone,severity,classification,"
                "confidence,status,data) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(run_id,incident_id) DO UPDATE SET updated=excluded.updated,severity=excluded.severity,"
                "classification=excluded.classification,confidence=excluded.confidence,status=excluded.status,"
                "data=excluded.data",
                (inc["id"], run_id, inc["created"], inc["updated"], inc["wall_time"], inc["zone"], inc["severity"],
                 inc["classification"], inc["confidence"], inc["status"], json.dumps(inc)))
            self.conn.commit()

    def upsert_response(self, run_id: str, r: dict) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO responses(id,run_id,sim_t,wall,incident_id,action,target,mode,status,data) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id,id) DO UPDATE SET status=excluded.status,"
                "data=excluded.data",
                (r["id"], run_id, r["t"], r.get("wall_time", ""), r.get("incident_id"), r["action"], r["target"],
                 r.get("mode"), r.get("status"), json.dumps(r)))
            self.conn.commit()

    def save_experiment(self, run_id: str, label: str, created: str, config: dict, metrics: dict,
                        status: str = "complete") -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO experiments(run_id,label,created,config,metrics,status) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET metrics=excluded.metrics,status=excluded.status,"
                "label=excluded.label",
                (run_id, label, created, json.dumps(config), json.dumps(metrics), status))
            self.conn.commit()

    # ------------------------------------------------------------------ reads
    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def events(self, run_id: str, limit: int = 500) -> list[dict]:
        rows = self._rows("SELECT * FROM events WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, limit))
        for r in rows:
            r["data"] = json.loads(r["data"] or "{}")
        return rows

    def experiments(self) -> list[dict]:
        rows = self._rows("SELECT * FROM experiments ORDER BY created DESC")
        for r in rows:
            r["config"] = json.loads(r["config"] or "{}")
            r["metrics"] = json.loads(r["metrics"] or "{}")
        return rows

    def experiment(self, run_id: str) -> Optional[dict]:
        rows = self._rows("SELECT * FROM experiments WHERE run_id=?", (run_id,))
        if not rows:
            return None
        r = rows[0]
        r["config"] = json.loads(r["config"] or "{}")
        r["metrics"] = json.loads(r["metrics"] or "{}")
        return r

    def alerts(self, run_id: str, limit: int = 500) -> list[dict]:
        rows = self._rows("SELECT * FROM alerts WHERE run_id=? ORDER BY sim_t DESC LIMIT ?", (run_id, limit))
        for r in rows:
            r["evidence"] = json.loads(r["evidence"] or "{}")
        return rows
