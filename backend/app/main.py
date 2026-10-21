"""FastAPI application: REST control/query endpoints + WebSocket telemetry.

Run:  uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api import models as M
from app.api.runtime import Runtime
from app.attacks.scenarios import catalog as attack_catalog
from app.experiments.runner import CONFIGS, ExperimentConfig, run_experiment
from app.network.protocols import PROTOCOL_INFO
from app.response.engine import ACTIONS as RESPONSE_ACTIONS
from app.simulation.plant import SUBSYSTEMS
from app.storage.database import Database

DB_PATH = os.environ.get("SCADA_DB", str(Path(__file__).resolve().parent.parent / "data" / "scada.db"))
SEED = int(os.environ.get("SCADA_SEED", "1337"))

db = Database(DB_PATH)
rt = Runtime(db, seed=SEED)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await rt.start_loop()
    try:
        yield
    finally:
        await rt.shutdown()
        db.close()


app = FastAPI(title="SCADA Digital-Twin Security Platform", version="1.0.0", lifespan=lifespan,
              description="Simulated industrial plant with SCADA/HMI, independent digital twin, multi-layer IDS, "
                          "physical watermarking, an attack lab and automated defensive responses. "
                          "All assets are simulated locally; this is an educational research demonstrator.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def eng():
    return rt.engine


# --------------------------------------------------------------------------- health / meta
@app.get("/api/health")
async def health() -> dict:
    e = eng()
    return {"status": "ok", "run_id": rt.run_id, "sim_time": e.show_t, "running": e.running, "speed": e.speed,
            "mode": "tripped" if e.safety.tripped else e.mode, "warmup_s": e.warmup_s,
            "clients": len(rt.hub.clients), "tick": e.tick_count,
            "disclaimer": "Educational simulation only — not a validated engineering or safety model."}


@app.get("/api/meta")
async def meta() -> dict:
    return {"subsystems": SUBSYSTEMS, "protocols": PROTOCOL_INFO, "scenarios": attack_catalog(),
            "detector_configs": {k: sorted(v["layers"]) for k, v in CONFIGS.items()},
            "watermark_targets": ["P-101", "FCV-101"], "seed": rt.seed,
            "response_actions": RESPONSE_ACTIONS}


# --------------------------------------------------------------------------- plant / devices
@app.get("/api/plant/state")
async def plant_state() -> dict:
    return eng().plant_state()


@app.get("/api/devices")
async def devices() -> dict:
    e = eng()
    return {"devices": e.plant.registry.to_list(),
            "controllers": [c.to_dict() for c in e.controllers.values()]}


@app.get("/api/devices/{device_id}")
async def device(device_id: str) -> dict:
    e = eng()
    if device_id in e.controllers:
        return {**e.controllers[device_id].to_dict(), "record_type": "controller"}
    d = e.plant.registry.devices.get(device_id)
    if d is None:
        raise HTTPException(404, f"no such device {device_id}")
    out = d.to_dict() if hasattr(d, "to_dict") else d.base_dict()
    return {**out, "record_type": "field_device"}


@app.get("/api/charts")
async def charts(keys: str = Query(default=""), points: int = Query(default=600, le=1800)) -> dict:
    k = [x for x in keys.split(",") if x] or None
    return eng().charts(k, points)


# --------------------------------------------------------------------------- network
@app.get("/api/network/topology")
async def topology() -> dict:
    e = eng()
    data = e.topo.to_dict()
    data["protocols"] = PROTOCOL_INFO
    data["quarantined"] = sorted(e.bus.quarantined)
    data["secure_channels"] = [sorted(p) for p in e.bus.secure_pairs]
    return data


@app.get("/api/network/traffic")
async def traffic(limit: int = Query(default=120, le=600)) -> dict:
    e = eng()
    msgs = list(e.bus.recent)[-limit:][::-1]
    return {"messages": msgs, "labels": e.ids.network.labels, "stats": e.ids.network.to_dict(),
            "events": e.bus.events[-40:]}


# --------------------------------------------------------------------------- digital twin
@app.get("/api/twin/state")
async def twin_state() -> dict:
    return eng().twin.to_dict()


# --------------------------------------------------------------------------- IDS
@app.get("/api/ids/alerts")
async def alerts(limit: int = Query(default=200, le=1000), active_only: bool = False,
                 severity: str = Query(default="")) -> dict:
    e = eng()
    data = e.ids.alerts(limit=limit, active_only=active_only)
    if severity:
        from app.core.util import sev_rank
        want = sev_rank(severity)
        data = [a for a in data if sev_rank(a["severity"]) >= want]
    return {"alerts": data, "active_count": len(e.ids.findings.active),
            "layers_enabled": e.ids.enabled}


@app.get("/api/ids/incidents")
async def incidents(limit: int = Query(default=50, le=200)) -> dict:
    return {"incidents": eng().ids.incidents(limit=limit)}


@app.post("/api/ids/layers")
async def toggle_layers(payload: dict) -> dict:
    e = eng()
    for k, v in payload.items():
        if k in e.ids.enabled:
            e.ids.enabled[k] = bool(v)
    return {"layers_enabled": e.ids.enabled}


@app.post("/api/ids/ack")
async def ack(req: M.AckRequest) -> dict:
    ok = await rt.with_lock(eng().ack_incident, req.incident_id)
    if not ok:
        raise HTTPException(404, "no such incident")
    return {"ok": True}


# --------------------------------------------------------------------------- watermarking
@app.get("/api/watermarking/state")
async def wm_state() -> dict:
    return eng().watermark.to_dict()


@app.post("/api/watermarking/enable")
async def wm_enable() -> dict:
    await rt.with_lock(lambda: eng().watermark.enable(eng().t))
    return {"ok": True, "enabled": True}


@app.post("/api/watermarking/disable")
async def wm_disable() -> dict:
    await rt.with_lock(lambda: eng().watermark.disable("disabled by operator"))
    return {"ok": True, "enabled": False}


@app.post("/api/watermarking/config")
async def wm_config(req: M.WatermarkConfigRequest) -> dict:
    kw = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        await rt.with_lock(lambda: eng().watermark.configure(**kw))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "config": eng().watermark.cfg.to_dict()}


# --------------------------------------------------------------------------- simulation control
@app.post("/api/simulation/start")
async def sim_start() -> dict:
    rt.start()
    return {"ok": True, "running": True}


@app.post("/api/simulation/pause")
async def sim_pause() -> dict:
    rt.pause()
    return {"ok": True, "running": False}


@app.post("/api/simulation/speed")
async def sim_speed(req: M.SpeedRequest) -> dict:
    rt.set_speed(req.speed)
    return {"ok": True, "speed": req.speed, "running": eng().running}


@app.post("/api/simulation/reset")
async def sim_reset(req: M.SimResetRequest) -> dict:
    await rt.reset(req.seed)
    return {"ok": True, "run_id": rt.run_id, "seed": rt.seed}


@app.post("/api/simulation/esd")
async def sim_esd() -> dict:
    await rt.with_lock(lambda: eng().safety.trigger_esd(eng().t))
    return {"ok": True, "message": "manual emergency shutdown (independent safety system)"}


@app.post("/api/simulation/esd/reset")
async def sim_esd_reset() -> dict:
    res = await rt.with_lock(lambda: eng().safety.reset(eng().t))
    return {"ok": True, **res}


@app.post("/api/simulation/maintenance")
async def maintenance(req: M.MaintenanceRequest) -> dict:
    await rt.with_lock(eng().set_maintenance, req.enabled)
    return {"ok": True, "maintenance": req.enabled}


# --------------------------------------------------------------------------- setpoints
@app.post("/api/control/setpoint")
async def set_setpoint(req: M.SetpointRequest) -> dict:
    e = eng()
    rec = await rt.with_lock(e.scada.write_setpoint, e.t, req.plc, req.register, req.value, req.user)
    if not rec["accepted"]:
        raise HTTPException(400, rec.get("reason") or "rejected")
    return {"ok": True, "record": rec}


# --------------------------------------------------------------------------- attacks
@app.get("/api/attacks")
async def attacks() -> dict:
    return eng().lab.status(eng().t)


@app.post("/api/attacks/start")
async def attack_start(req: M.AttackStartRequest) -> dict:
    e = eng()
    try:
        res = await rt.with_lock(e.lab.start, req.scenario, req.params, e.t)
    except KeyError:
        raise HTTPException(404, f"unknown scenario {req.scenario}")
    if not res.get("ok"):
        raise HTTPException(409, res.get("error", "could not start"))
    return res


@app.post("/api/attacks/stop")
async def attack_stop(req: M.AttackStopRequest) -> dict:
    e = eng()
    res = await rt.with_lock(e.lab.stop, req.scenario, e.t)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error", "not running"))
    return res


@app.post("/api/attacks/stop_all")
async def attack_stop_all() -> dict:
    e = eng()
    await rt.with_lock(e.lab.stop_all, e.t)
    return {"ok": True}


# --------------------------------------------------------------------------- response engine
@app.get("/api/response")
async def response_state() -> dict:
    return eng().response.to_dict()


@app.post("/api/response/mode")
async def response_mode(req: M.ResponseModeRequest) -> dict:
    await rt.with_lock(eng().response.set_mode, req.mode)
    return {"ok": True, "mode": req.mode}


@app.post("/api/response/approve")
async def response_approve(req: M.ApproveRequest) -> dict:
    e = eng()

    def _do():
        if req.approve:
            return e.response.approve(e.t, req.response_id, req.operator, e.ids.correlation.incidents.get)
        return e.response.reject(e.t, req.response_id, req.operator)

    res = await rt.with_lock(_do)
    if not res.get("ok"):
        raise HTTPException(404, res.get("error", "no such response"))
    return res


# --------------------------------------------------------------------------- experiments
@app.get("/api/experiments")
async def experiments() -> dict:
    return {"experiments": db.experiments(), "presets": list(CONFIGS.keys())}


@app.get("/api/experiments/{run_id}")
async def experiment(run_id: str) -> dict:
    ex = db.experiment(run_id)
    if ex is None:
        raise HTTPException(404, "no such experiment")
    return ex


@app.post("/api/experiments/run")
async def experiment_run(req: M.ExperimentRunRequest) -> dict:
    cfg = ExperimentConfig(
        label=req.label or (f"{req.scenario or 'normal'} (seed {req.seed})"),
        seed=req.seed, scenario=req.scenario, scenario_params=req.params, watermark=req.watermark,
        attack_at=req.attack_at, attack_stop=req.attack_stop, duration=req.duration,
        response_mode=req.response_mode, bin_s=req.bin_s)
    result = await rt.run_experiment_async(cfg)
    return result


@app.get("/api/events")
async def events(limit: int = Query(default=200, le=1000)) -> dict:
    return {"events": db.events(rt.run_id, limit=limit)}


@app.get("/api/export/{kind}")
async def export(kind: str) -> PlainTextResponse:
    import csv
    import io
    e = eng()
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "alerts":
        w.writerow(["id", "sim_t", "asset", "severity", "category", "source", "rule", "score", "status"])
        for a in e.ids.alerts(limit=1000):
            w.writerow([a["id"], a["timestamp"], a["asset"], a["severity"], a["category"], a["source"], a["rule"],
                        a.get("score"), a["status"]])
    elif kind == "telemetry":
        ch = e.charts(points=1800)
        keys = list(ch["series"].keys())
        w.writerow(["t"] + keys)
        for i, t in enumerate(ch["t"]):
            w.writerow([t] + [ch["series"][k][i] if i < len(ch["series"][k]) else "" for k in keys])
    else:
        raise HTTPException(404, "export kind must be alerts|telemetry")
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={kind}.csv"})


# --------------------------------------------------------------------------- websocket
@app.websocket("/ws")
async def ws(ws: WebSocket) -> None:
    await ws.accept()
    q = rt.hub.connect()
    try:
        await ws.send_json({"type": "hello", "data": {"run_id": rt.run_id, "snapshot": eng().snapshot()}})
        while True:
            msg = await q.get()
            await ws.send_json(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        rt.hub.disconnect(q)


@app.get("/api")
async def api_root() -> dict:
    return {"name": "SCADA Digital-Twin Security Platform", "docs": "/docs", "health": "/api/health",
            "websocket": "/ws"}


# --------------------------------------------------------------------------- static frontend (optional)
# When the frontend has been built (`npm run build`), serve it from the same origin so the
# whole platform runs from one command: `uvicorn app.main:app`. During development, use the
# Vite dev server (port 5173), which proxies /api and /ws back here.
_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _DIST.is_dir():
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse

    # index.html must never be cached by the browser: it is the small shell that points at
    # the content-hashed JS/CSS bundles. If it is cached, a rebuild (new bundle hashes) is
    # never picked up. The hashed assets themselves are immutable and cache freely.
    _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}

    @app.get("/")
    async def _index() -> FileResponse:
        return FileResponse(_DIST / "index.html", headers=_NO_CACHE)

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="static")
else:
    @app.get("/")
    async def root() -> dict:
        return {"name": "SCADA Digital-Twin Security Platform", "docs": "/docs", "health": "/api/health",
                "websocket": "/ws", "note": "frontend/dist not built; use the Vite dev server on :5173"}
