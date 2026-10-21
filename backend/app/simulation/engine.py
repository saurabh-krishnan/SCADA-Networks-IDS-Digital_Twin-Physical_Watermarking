"""Simulation engine: the per-tick orchestration of the whole platform.

Tick order (dt, default 0.1 s = 10 Hz):
  1. attack lab manipulations (interceptors/injections/firmware hooks installed)
  2. physical plant integrates from the *real* actuator outputs
  3. hard-wired SIS reads the real state and may trip final elements
  4. field devices report sampled telemetry; PLCs scan and command actuators
  5. network bus delivers all messages scheduled up to this tick
  6. SCADA polling / historian / twin feeds (driven by the bus)
  7. digital twin propagates + residuals; watermark engine updates
  8. IDS layers run; findings -> correlation -> response engine
  9. telemetry snapshot assembled for the UI / experiment recorder

The engine is transport-agnostic: it exposes ``snapshot()`` and per-view dumps
that the API and the experiment runner both consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.attacks.context import AttackContext, PhysicalAccess
from app.attacks.injector import AttackLab
from app.core.rng import SeedBank
from app.core.util import RollingStats, now_iso, r
from app.digital_twin.model import TwinParams
from app.digital_twin.prediction import DigitalTwin
from app.ids.consistency import BoilerConsistency
from app.ids.manager import IDS
from app.ids.network_detector import NetworkDetector
from app.ids.process_detector import ProcessDetector
from app.ids.twin_detector import TwinDetector
from app.ids.watermark_detector import WatermarkDetector
from app.network.topology import build_topology
from app.network.traffic import Message, NetworkBus
from app.response.engine import ResponseEngine
from app.simulation.boiler import BoilerParams, cover_pressure
from app.simulation.plant import SUBSYSTEMS, Plant
from app.simulation.programs import build_controllers
from app.simulation.safety import SafetySystem
from app.simulation.scada import (AuthServer, Historian, IdentityService, MqttBroker, OPERATING_ENVELOPE,
                                   ROLE_PERMISSIONS, ScadaServer, USERS, Workstation)
from app.simulation.wiring import (build_allowed_flows, build_authorized_writers, build_inventory,
                                   build_register_maps, register_owner_map)
from app.watermarking.engine import WatermarkConfig, WatermarkEngine


@dataclass
class EngineConfig:
    seed: int = 1337
    dt: float = 0.1
    telemetry_buffer: int = 1800  # 3 min at 10 Hz
    watermark: WatermarkConfig = field(default_factory=WatermarkConfig)
    boiler: BoilerParams = field(default_factory=BoilerParams)
    twin: TwinParams = field(default_factory=TwinParams)
    record_traffic: bool = True


class SimulationEngine:
    def __init__(self, config: Optional[EngineConfig] = None):
        self.cfg = config or EngineConfig()
        self.build()

    # ------------------------------------------------------------------ assembly
    def build(self) -> None:
        cfg = self.cfg
        self.seeds = SeedBank(cfg.seed)
        self.t = 0.0
        self.tick_count = 0
        self.display_t0 = 0.0
        self.warmup_s = 0.0
        self.plant = Plant(self.seeds, cfg.boiler)
        self.safety = SafetySystem(self.plant, self.seeds)
        self.controllers = build_controllers(self.plant)
        self.topo = build_topology(self.plant.field_devices_by_controller())
        self.bus = NetworkBus(self.topo, cfg.seed)
        self.bus.record = cfg.record_traffic
        self.register_maps = build_register_maps(self.controllers)
        self.identity = IdentityService()
        self.scada = ScadaServer(self.bus, self.register_maps, self.plant.registry, self.identity)
        self.hmi = Workstation("HMI-01", self.bus, self.identity)
        self.ews = Workstation("EWS-01", self.bus, self.identity)
        self.historian = Historian(self.bus)
        self.broker = MqttBroker(self.bus)
        self.auth = AuthServer(self.bus, self.identity)
        for cid, plc in self.controllers.items():
            plc.bus = self.bus
            self.bus.register(cid, plc.on_message)
        for sid, sensor in self.plant.sensors.items():
            self.bus.register(sid, lambda m: None)
        for aid in self.plant.actuators:
            self.bus.register(aid, self._make_actuator_handler(aid))
        # secure-channel option (used by failover response): SCADA <-> each PLC
        self.secure_available = {("SCADA-01", cid) for cid in self.controllers}
        # digital twin
        self.twin = DigitalTwin(TwinParams(**cfg.twin.to_dict()) if isinstance(cfg.twin, TwinParams) else cfg.twin)
        self.bus.register("TWIN-01", self._twin_on_message)
        # watermark engine (PLC-1 pulls offsets through this hook)
        self.watermark = WatermarkEngine(self.twin.params, cfg.dt, cfg.watermark)
        self.controllers["PLC-1"].watermark_hook = self.watermark.offset_for
        # IDS
        policy = {"maintenance": False}
        self.policy = policy
        self.consistency = BoilerConsistency(self.twin.params)
        net = NetworkDetector(build_inventory(self.topo), build_allowed_flows(self.controllers),
                              build_authorized_writers(self.controllers), self.register_maps, OPERATING_ENVELOPE,
                              {u: USERS[u]["role"] for u in USERS}, policy)
        self.bus.span_taps.append(net.on_mirror)
        proc = ProcessDetector(list(self.plant.sensors.values()),
                               {a.id: a.kind for a in self.plant.actuators.values()},
                               register_owner_map(self.controllers))
        self.process_detector = proc
        twindet = TwinDetector(self.twin, proc.consistency)
        wmdet = WatermarkDetector(self.watermark)
        self.ids = IDS(net, proc, twindet, wmdet)
        # attack lab
        ctx = AttackContext(self.bus, self.topo, self.plant.sensors, self.plant.actuators, self.ews,
                            self.register_maps,
                            PhysicalAccess(lambda f: setattr(self.plant.boiler, "hx_fouling", f),
                                           lambda: self.plant.boiler.hx_fouling),
                            self._lab_restore_setpoints, self._lab_login, self._lab_logout)
        self.lab = AttackLab(ctx, cfg.seed)
        # response engine
        self.response = ResponseEngine(self._response_hooks())
        # telemetry buffers
        self.telemetry: dict[str, RollingStats] = {}
        self.buffers: dict[str, list] = {}
        self.time_axis: list[float] = []
        self._buf_keys = (list(self.plant.sensors.keys()) +
                          ["gen.P", "gen.freq", "sec.Q_turb", "wt.L_tw", "mix.T", "pipe.Q",
                           "twin.TT-101", "twin.FT-101", "res.TT-101", "res.FT-101", "wm.e_flow", "wm.o_flow"])
        for k in self._buf_keys:
            self.buffers[k] = []
        self.running = False
        self.speed = 1.0
        self.sim_speed_target = 1.0
        self.events_sink: Optional[Callable[[dict], None]] = None
        self.alert_sink: Optional[Callable[[str, Any], None]] = None
        self.last_new_alerts: list[dict] = []
        self.history_wm_enabled_at: Optional[float] = None
        self.mode = "running"
        self._compromised_accounts: set[str] = set()
        self._warmup()

    @property
    def show_t(self) -> float:
        """Displayed time: simulation seconds since the warm-up completed."""
        return round(self.t - self.display_t0, 2)

    def _make_actuator_handler(self, aid: str) -> Callable[[Message], None]:
        act = self.plant.actuators[aid]
        plc = self.controllers[act.controller]

        def handler(msg: Message) -> None:
            if msg.kind == "AO_WRITE":
                act.set_command(msg.payload["value"])
        return handler

    def _warmup(self) -> None:
        """Run a silent warm-up so controllers, twin calibration and detector learning
        windows settle before the displayed timeline starts.

        The simulation clock runs *continuously* through warm-up (resetting it would
        leave every absolute-time scheduler — SCADA polling, historian/twin feeds,
        residual calibration — pointing into the future). Only the displayed time is
        offset so the UI timeline begins at 0, and only the chart buffers are cleared.
        """
        self.warmup_s = 45.0
        for _ in range(int(self.warmup_s / self.cfg.dt)):
            self._tick(record=False)
        self.display_t0 = self.t
        for k in self.buffers:
            self.buffers[k] = []
        self.time_axis = []

    # ------------------------------------------------------------------ lab callbacks
    def _lab_restore_setpoints(self, t: float) -> None:
        for reg, val in self.scada.approved.items():
            plc = self.scada.tag_plc.get(reg)
            if plc:
                self.scada.write_setpoint(t + 0.01, plc, reg, val, "scada-svc", approve=False, trusted=True)

    def _lab_login(self, node: str, user: str, t: float) -> None:
        ws = {"HMI-01": self.hmi, "EWS-01": self.ews}.get(node)
        if ws:
            ws.login(t, user)

    def _lab_logout(self, node: str, t: float) -> None:
        self.identity.logout(node, t)

    # ------------------------------------------------------------------ twin config endpoint
    def _twin_on_message(self, msg: Message) -> None:
        if msg.protocol == "opcua" and msg.payload.get("service") == "WriteRequest":
            node = msg.payload["nodesToWrite"][0]
            self.twin.apply_config(node["nodeId"], node["value"], msg.src, msg.user, msg.t_deliver)

    # ------------------------------------------------------------------ response hooks (simulated effects only)
    def _response_hooks(self) -> dict[str, Callable[..., Any]]:
        def quarantine(t, target, inc):
            node = target
            if target.startswith("mac:"):
                node = next((n.id for n in self.topo.nodes.values() if n.mac == target[4:]), None)
            if node and node in self.topo.nodes:
                self.bus.quarantined.add(node)
                self.topo.nodes[node].hidden = False
                d = self.plant.registry.devices.get(node)
                if d:
                    d.quarantined = True
                return {"quarantined": node}
            return {"note": f"no such endpoint {target}"}

        def allowlist(t, target, inc):
            plc = self.controllers.get(target)
            if plc:
                plc.allowlist_enforced = True
                return {"allowlist_enforced": target}
            for p in self.controllers.values():
                p.allowlist_enforced = True
            return {"allowlist_enforced": "all"}

        def restore(t, target, inc):
            plc = self.scada.tag_plc.get(target)
            if plc and target in self.scada.approved:
                self.scada.write_setpoint(t + 0.01, plc, target, self.scada.approved[target], "scada-svc",
                                          approve=False, trusted=True)
                return {"restored": target, "value": self.scada.approved[target]}
            return {"note": f"no approved value for {target}"}

        def disable_user(t, target, inc):
            revoked = self.identity.disable(target, t)
            self._compromised_accounts.add(target)
            return {"disabled": target, "revoked_sessions": revoked}

        def mark(t, target, inc):
            d = self.plant.registry.devices.get(target)
            if d:
                d.suspicious = True
            self.scada.tags.pop(target, None)  # drop the untrusted tag; twin estimate fills the gap in the UI
            return {"marked_suspicious": target}

        def failover(t, target, inc):
            plc = target if target in self.controllers else "PLC-1"
            self.bus.secure_pairs.add(frozenset(("SCADA-01", plc)))
            return {"secure_channel": ["SCADA-01", plc]}

        def safe_state(t, target, inc):
            self.scada.write_setpoint(t + 0.01, "PLC-1", "TIC-101.SP", 430.0, "scada-svc", trusted=True)
            self.scada.write_setpoint(t + 0.02, "PLC-1", "P-101.SP", 90.0, "scada-svc", trusted=True)
            return {"safe_state": "reduced thermal load", "TIC-101.SP": 430.0}

        def resync(t, target, inc):
            self.twin.phys.hx_scale = 1.0
            self.twin.params = TwinParams()
            self.twin.phys.p = self.twin.params
            obs = {k: self.scada.tags[k][0] for k in self.twin.trackers if k in self.scada.tags}
            cmd = self._issued_commands()
            self.twin.synchronize(obs, cmd, t, reason="response resync")
            return {"resynced": True}

        def preserve(t, target, inc):
            snap = {"t": round(t, 2), "incident": inc.id if inc else None,
                    "alerts": self.ids.alerts(limit=50), "traffic": list(self.bus.recent)[-80:]}
            self._last_evidence = snap
            return {"evidence_snapshot": True, "alerts": len(snap["alerts"])}

        def pause(t, target, inc):
            self.running = False
            return {"paused": True}

        return {"quarantine_endpoint": quarantine, "reject_unauthorized_commands": allowlist,
                "restore_setpoint": restore, "disable_user": disable_user, "mark_suspicious": mark,
                "failover_secure_channel": failover, "enter_safe_state": safe_state, "resync_twin": resync,
                "preserve_evidence": preserve, "pause_experiment": pause}

    def _issued_commands(self) -> dict[str, float]:
        return {aid: a.command for aid, a in self.plant.actuators.items()}

    # ------------------------------------------------------------------ one tick
    def _tick(self, record: bool = True) -> list[dict]:
        dt = self.cfg.dt
        t = self.t
        self.lab.tick(t, dt)                     # 1. attacker manipulations
        self.plant.step(dt)                      # 2. physical plant (real actuator outputs)
        sis_events = self.safety.evaluate(t)     # 3. hard-wired safety
        self._field_io(t)                        # 4. field telemetry + PLC scans
        self.bus.run_until(t + dt - 1e-9)        # 5. deliver messages
        self.scada.tick(t)                       # 6. supervisory polling / feeds
        self._feed_twin_and_watermark(t, dt)     # 7. twin + watermark
        alarm_events = self.scada.evaluate(t) if self.tick_count % 5 == 0 else []
        events = self.ids.step(t, self.scada, self.scada.approved)  # 8. IDS + correlation
        self._drive_response(t, events, sis_events, alarm_events)
        if record:
            self._record(t)
        self.t = round(self.t + dt, 6)
        self.tick_count += 1
        return events

    def _field_io(self, t: float) -> None:
        for sid, sensor in self.plant.sensors.items():
            if self.tick_count % sensor.sample_every:
                continue
            true_v = self.plant.physical[sensor.variable]
            val = sensor.sample(t, true_v)
            plc = self.controllers[sensor.controller]
            self.bus.send(Message(t, sid, sensor.controller, "field", "AI_REPORT",
                                  {"tag": sid, "value": round(val, 5)}))
        for aid, act in self.plant.actuators.items():
            if self.tick_count % 5 == 0:
                self.bus.send(Message(t, aid, act.controller, "field", "AO_STATUS",
                                      {"tag": aid, "feedback": round(act.feedback, 4)}))
        self.bus.run_until(t + 0.02)  # let field reports reach PLCs before the scan
        for plc in self.controllers.values():
            plc.scan(t, self.cfg.dt)
        if self.tick_count % 10 == 0:
            self.bus.roll_stats(1.0)

    def _feed_twin_and_watermark(self, t: float, dt: float) -> None:
        tags = self.scada.tags
        obs = {k: (tags[k][0], self.scada.quality(k, t) == "good") for k in self.twin.trackers if k in tags}
        for k in ("TT-101", "TT-102", "TT-103", "FT-101", "TT-201", "TT-202", "FT-201", "PT-101", "PT-102"):
            obs.setdefault(k, (float("nan"), False))
        base_cmd = {"P-101": self.scada.approved.get("P-101.SP", 85.0),
                    "FCV-101": self.scada.approved.get("FCV-101.SP", 80.0),
                    "P-201": self.scada.approved.get("P-201.SP", 80.0)}
        heater = tags.get("JT-101", [self.plant.actuators["HTR-101"].output * 25.0])[0]
        gen = tags.get("JT-201", [self.plant.boiler.P_gen])[0]
        fan = tags.get("FAN-201.FB", [self.plant.actuators["FAN-201"].output])[0]
        self.twin.step(t, dt, self._issued_commands(), {"heater_kw": heater, "fan_pct": fan, "gen_kw": gen}, obs)
        # watermark engine: expected (shadow models) vs observed (telemetry)
        q_bad = sum(1 for k in ("FT-101", "PT-101") if not obs.get(k, (0, False))[1]) / 2.0
        self.watermark.ctx.update({
            "sis_tripped": self.safety.tripped,
            "flow_local": self.plant.physical["boiler.m"],
            "thl_local": self.plant.physical["boiler.T_hl"],
            "quality_bad_frac": q_bad,
            "mode_manual": self.scada.approved.get("TIC-101.MODE", 1.0) < 0.5,
        })
        tp = self.twin.params
        p_cover_est = tp.p_cover0 + tp.p_cover_beta * (self.twin.phys.x["T_b"] - tp.t_ref)
        self.watermark.update(t, base_cmd, obs, p_cover_est)

    def _drive_response(self, t: float, events: list, sis_events: list, alarm_events: list) -> None:
        self.changed_incidents = self.ids.correlation.drain_changed()
        targets = list(self.changed_incidents)
        if self.response.mode != "monitor":
            # also (re)offer responses for any still-open incident, so a mode change or a
            # not-yet-actioned recommendation is picked up even without a fresh finding
            seen = {i.id for i in targets}
            targets += [i for i in self.ids.correlation.incidents.values()
                        if i.status in ("open", "acknowledged", "responding") and i.id not in seen]
        for inc in targets:
            items = self.response.handle_incident(t, inc)
            if items:
                for r in items:
                    if self.events_sink:
                        self.events_sink({"category": "response", "source": "response_engine",
                                          "severity": "info", "message": f"{r['status']}: {r['action']} → "
                                          f"{r['target']}", "data": {"incident_id": inc.id}})
                if self.alert_sink:
                    self.alert_sink("responses", items)
        # collect newly raised alerts for streaming / persistence
        new = []
        for kind, f in events:
            if kind == "raised" and f.severity != "info":
                new.append(f.to_dict())
                if self.events_sink:
                    self.events_sink({"category": "alert", "source": f.layer, "severity": f.severity,
                                      "message": f"{f.category} on {f.asset}",
                                      "data": {"alert_id": f.id, "rule": f.rule}})
        self.last_new_alerts = new
        for ev in sis_events:
            if self.events_sink:
                self.events_sink({"category": "safety", "source": "SIS", "severity": "critical",
                                  "message": f"Safety trip {ev['rule']}: {ev['desc']}", "data": ev})

    # ------------------------------------------------------------------ recording
    def _record(self, t: float) -> None:
        keep = self.cfg.telemetry_buffer
        self.time_axis.append(round(t - self.display_t0, 2))
        tags = self.scada.tags
        for sid in self.plant.sensors:
            v = tags[sid][0] if sid in tags else None
            self.buffers[sid].append(r(v, 4))
        phys = self.plant.physical
        for k in ("gen.P", "gen.freq", "sec.Q_turb", "wt.L_tw", "mix.T", "pipe.Q"):
            self.buffers[k].append(r(phys.get(k), 4))
        self.buffers["twin.TT-101"].append(r(self.twin.pred.get("TT-101")))
        self.buffers["twin.FT-101"].append(r(self.twin.pred.get("FT-101")))
        self.buffers["res.TT-101"].append(r(self.twin.trackers["TT-101"].r))
        self.buffers["res.FT-101"].append(r(self.twin.trackers["FT-101"].r))
        wm = self.watermark.history[-1] if self.watermark.history else None
        self.buffers["wm.e_flow"].append(wm[2] if wm else None)
        self.buffers["wm.o_flow"].append(wm[3] if wm else None)
        if len(self.time_axis) > keep:
            self.time_axis = self.time_axis[-keep:]
            for k in self.buffers:
                self.buffers[k] = self.buffers[k][-keep:]

    # ------------------------------------------------------------------ public control
    def step_many(self, n: int) -> list[dict]:
        allev = []
        for _ in range(n):
            allev += self._tick()
        return allev

    def reset(self) -> None:
        self.build()

    def set_maintenance(self, on: bool) -> None:
        self.policy["maintenance"] = on

    def ack_incident(self, inc_id: str) -> bool:
        inc = self.ids.correlation.incidents.get(inc_id)
        if inc:
            inc.acknowledged = True
            if inc.status == "open":
                inc.status = "acknowledged"
            return True
        return False

    # ------------------------------------------------------------------ views
    def plant_state(self) -> dict:
        sens = {}
        for sid, s in self.plant.sensors.items():
            e = self.scada.tags.get(sid)
            sens[sid] = {
                "name": s.name, "subsystem": s.subsystem, "unit": s.unit, "value": r(e[0], 4) if e else None,
                "quality": self.scada.quality(sid, self.t) if e else "no data",
                "alarm": s.alarm_state, "limits": s.limits.to_dict(), "range": [s.range_lo, s.range_hi],
                "suspicious": s.suspicious,
            }
        acts = {aid: {"name": a.name, "kind": a.kind, "subsystem": a.subsystem, "unit": a.unit,
                      "command": r(a.command, 2), "output": r(a.output, 2), "feedback": r(a.feedback, 2),
                      "tripped": a.trip_override is not None, "suspicious": a.suspicious}
                for aid, a in self.plant.actuators.items()}
        return {
            "t": self.show_t, "sim_t": round(self.t, 2), "running": self.running, "speed": self.speed,
            "tick": self.tick_count,
            "mode": "tripped" if self.safety.tripped else self.mode,
            "subsystems": SUBSYSTEMS, "sensors": sens, "actuators": acts,
            "physical_debug": {k: r(v, 4) for k, v in self.plant.physical.items()},
            "safety": self.safety.to_dict(),
            "controllers": {cid: {"phase": c.state, "rejected_writes": c.rejected_writes,
                                  "allowlist": c.allowlist_enforced} for cid, c in self.controllers.items()},
            "batch_phase": int(self.controllers["PLC-4"].state.get("BATCH.PHASE", 0)),
            "load_demand_kw": r(self.plant.boiler.load_demand_kw, 1),
        }

    def charts(self, keys: Optional[list[str]] = None, points: int = 600) -> dict:
        keys = keys or self._buf_keys
        n = len(self.time_axis)
        start = max(0, n - points)
        return {"t": self.time_axis[start:], "series": {k: self.buffers.get(k, [])[start:] for k in keys}}

    def snapshot(self) -> dict:
        """Compact per-tick snapshot pushed over the WebSocket."""
        tags = self.scada.tags
        live = {sid: r(tags[sid][0], 4) for sid in self.plant.sensors if sid in tags}
        acts = {aid: r(a.output, 2) for aid, a in self.plant.actuators.items()}
        inc = sorted(self.ids.correlation.incidents.values(), key=lambda i: -i.updated)[:6]
        return {
            "t": self.show_t, "sim_t": round(self.t, 2), "running": self.running, "speed": self.speed,
            "mode": "tripped" if self.safety.tripped else self.mode,
            "sensors": live, "actuators": acts,
            "alarms": list(self.scada.alarms.values()),
            "twin": {"confidence": round(self.twin.confidence, 3), "health": self.twin.health,
                     "sync": self.twin.sync_status, "anomaly_score": round(self.twin.anomaly_score(), 3),
                     "residuals": {k: r(self.twin.trackers[k].z) for k in ("TT-101", "FT-101", "TT-201")}},
            "watermark": {"enabled": self.watermark.enabled, "injecting": self.watermark.injecting,
                          "decision": self.watermark.decision, "alarm": self.watermark.alarm,
                          "offset": r(self.watermark._applied, 3)},
            "ids": {"active_alerts": len(self.ids.findings.active),
                    "active_layers": sorted(self.ids.findings.active_layers()),
                    "open_incidents": sum(1 for i in self.ids.correlation.incidents.values()
                                          if i.status not in ("resolved",))},
            "incidents": [i.to_dict() for i in inc],
            "lab": {"running": [s.meta.key for s in self.lab.running.values()],
                    "ground_truth": self.lab.any_effect_active(self.t)},
            "safety": {"tripped": self.safety.tripped, "latched": [x["rule"] for x in self.safety.latched.values()]},
            "response_mode": self.response.mode,
            "new_alerts": self.last_new_alerts,
        }
