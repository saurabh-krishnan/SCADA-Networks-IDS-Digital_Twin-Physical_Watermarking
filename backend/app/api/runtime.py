"""Live simulation runtime: owns the engine, runs the real-time loop in a
background task, persists events and broadcasts snapshots over WebSocket.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Optional

from app.core.util import now_iso
from app.experiments.runner import ExperimentConfig, run_experiment
from app.simulation.engine import EngineConfig, SimulationEngine
from app.storage.database import Database


class Hub:
    """Fan-out of JSON snapshots to connected WebSocket clients."""

    def __init__(self) -> None:
        self.clients: set[asyncio.Queue] = set()

    def connect(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=20)
        self.clients.add(q)
        return q

    def disconnect(self, q: asyncio.Queue) -> None:
        self.clients.discard(q)

    def broadcast(self, message: dict) -> None:
        for q in list(self.clients):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(message)


class Runtime:
    def __init__(self, db: Database, seed: int = 1337):
        self.db = db
        self.seed = seed
        self.run_id = f"run-{int(time.time())}"
        self.engine = SimulationEngine(EngineConfig(seed=seed))
        self.hub = Hub()
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self.tps = 10.0  # target ticks per second at speed 1.0
        self._experiment_task: Optional[asyncio.Task] = None
        self.experiment_progress: dict = {"running": False}
        self.engine.events_sink = self._on_event
        self.last_snapshot: dict = {}
        self._persist_counter = 0

    # ------------------------------------------------------------------ loop
    async def start_loop(self) -> None:
        self._stop.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def shutdown(self) -> None:
        self._stop.set()
        if self._task:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def _on_event(self, ev: dict) -> None:
        self.db.log_event(self.run_id, round(self.engine.show_t, 2), now_iso(), ev["category"], ev["source"],
                          ev["severity"], ev["message"], ev.get("data"))

    async def _run(self) -> None:
        dt = self.engine.cfg.dt
        next_t = time.perf_counter()
        while not self._stop.is_set():
            speed = self.engine.speed if self.engine.running else 0.0
            if speed <= 0:
                await asyncio.sleep(0.05)
                next_t = time.perf_counter()
                # still push a heartbeat snapshot ~5 Hz so paused UIs stay fresh
                self._emit()
                await asyncio.sleep(0.15)
                continue
            n_ticks = max(1, int(round(speed)))
            async with self._lock:
                self.engine.step_many(n_ticks)
                self._persist()
                self._emit()
            period = n_ticks / (self.tps * max(speed, 1.0)) if speed >= 1 else dt / speed
            next_t += period
            delay = next_t - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                next_t = time.perf_counter()

    def _emit(self) -> None:
        snap = self.engine.snapshot()
        snap["run_id"] = self.run_id
        self.last_snapshot = snap
        self.hub.broadcast({"type": "snapshot", "data": snap})

    def _persist(self) -> None:
        self._persist_counter += 1
        if self._persist_counter % 5:  # persist alerts/incidents ~2 Hz
            return
        for f in self.engine.ids.findings.all[-30:]:
            self.db.upsert_alert(self.run_id, f.to_dict())
        for inc in getattr(self.engine, "changed_incidents", []):
            self.db.upsert_incident(self.run_id, inc.to_dict())
        for r in self.engine.response.history:
            if r.get("status") in ("executed", "pending_approval", "rejected", "failed"):
                self.db.upsert_response(self.run_id, r)

    # ------------------------------------------------------------------ controls
    async def with_lock(self, fn, *a, **kw):
        async with self._lock:
            return fn(*a, **kw)

    def start(self) -> None:
        self.engine.running = True
        if self.engine.speed <= 0:
            self.engine.speed = 1.0

    def pause(self) -> None:
        self.engine.running = False

    def set_speed(self, speed: float) -> None:
        self.engine.speed = speed
        self.engine.running = speed > 0

    async def reset(self, seed: Optional[int] = None) -> None:
        async with self._lock:
            self.seed = seed if seed is not None else self.seed
            self.engine = SimulationEngine(EngineConfig(seed=self.seed))
            self.engine.events_sink = self._on_event
            self.run_id = f"run-{int(time.time())}"
            self._emit()

    # ------------------------------------------------------------------ experiments
    async def run_experiment_async(self, cfg: ExperimentConfig) -> dict:
        loop = asyncio.get_running_loop()
        self.experiment_progress = {"running": True, "label": cfg.label, "progress": 0.0}

        def progress(p: float) -> None:
            self.experiment_progress["progress"] = round(p, 3)
            self.hub.broadcast({"type": "experiment_progress", "data": dict(self.experiment_progress)})

        result = await loop.run_in_executor(None, lambda: run_experiment(cfg, progress))
        run_id = f"exp-{int(time.time())}"
        self.db.save_experiment(run_id, cfg.label, result["created"], cfg.to_dict(), result)
        result["run_id"] = run_id
        self.experiment_progress = {"running": False, "progress": 1.0}
        self.hub.broadcast({"type": "experiment_done", "data": {"run_id": run_id, "label": cfg.label}})
        return result
