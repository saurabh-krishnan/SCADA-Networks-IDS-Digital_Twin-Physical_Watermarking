"""Fault / anomaly scenarios for the IDS detection testbed (simulated assets only).

Each scenario is a reproducible disturbance used to *exercise the detectors*.
It touches the simulation only through ``AttackContext`` (message interceptors,
injected telemetry frames, field-device firmware hooks, a compromised
workstation session, or a physical degradation). It never reaches the safety
system, the digital twin, the watermark engine or the IDS.

``effect_active(t)`` is the ground-truth label consumed by the experiment
evaluator: it is True only while the scenario is actively manipulating the
simulation (a passive recording phase, if any, is not labelled positive).

Design invariant exercised by several scenarios: the *physical* plant keeps
evolving from the real actuator outputs, while only the *observed* telemetry (or
a field device's behaviour) is altered. That gap is exactly what the independent
twin, the redundancy checks and the watermark are meant to expose.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.attacks.context import AttackContext
from app.network import protocols as mb
from app.network.traffic import Interceptor, Message


@dataclass
class ScenarioMeta:
    key: str
    name: str
    category: str
    description: str
    preconditions: str
    target_assets: list[str]
    expected_evidence: list[str]
    params: dict[str, Any] = field(default_factory=dict)


class Scenario:
    """Base class. Subclasses implement start/stop and (optionally) per-tick work."""

    meta: ScenarioMeta

    def __init__(self, ctx: AttackContext, params: dict[str, Any], seed: int):
        self.ctx = ctx
        self.params = {**self.meta.params, **(params or {})}
        self.seed = seed
        self.t_start: Optional[float] = None
        self.t_stop: Optional[float] = None
        self.active = False
        self.log: list[dict] = []

    # lifecycle ---------------------------------------------------------------
    def start(self, t: float) -> None:
        self.t_start = t
        self.active = True
        self.log.append({"t": round(t, 2), "event": "scenario started", "params": self.params, "seed": self.seed})
        self.on_start(t)

    def stop(self, t: float) -> None:
        if not self.active:
            return
        self.active = False
        self.t_stop = t
        self.on_stop(t)
        self.log.append({"t": round(t, 2), "event": "scenario stopped / recovered"})

    def tick(self, t: float, dt: float) -> None:
        if self.active:
            self.on_tick(t, dt)

    # hooks -------------------------------------------------------------------
    def on_start(self, t: float) -> None: ...
    def on_stop(self, t: float) -> None: ...
    def on_tick(self, t: float, dt: float) -> None: ...

    def effect_active(self, t: float) -> bool:
        return self.active

    def note(self, t: float, msg: str, **kw) -> None:
        self.log.append({"t": round(t, 2), "event": msg, **kw})

    def status(self, t: float) -> dict:
        return {
            "key": self.meta.key, "name": self.meta.name, "category": self.meta.category,
            "active": self.active, "effect_active": self.effect_active(t),
            "t_start": self.t_start, "t_stop": self.t_stop,
            "elapsed": round(t - self.t_start, 1) if self.t_start is not None and self.active else None,
            "params": self.params, "seed": self.seed, "target_assets": self.meta.target_assets,
            "expected_evidence": self.meta.expected_evidence, "log": self.log[-30:],
        }


# ---------------------------------------------------------------------------
# Telemetry manipulation (observation layer): the physical plant is untouched;
# only the values reported to SCADA are altered. Exposes the twin / redundancy.
# ---------------------------------------------------------------------------
class FalseDataInjection(Scenario):
    meta = ScenarioMeta(
        key="false_data_injection", name="False sensor data injection", category="process_falsification",
        description="A sensor's reported value is overwritten with a fabricated reading while the real process "
                    "continues normally. The operator sees a benign number; the twin and redundancy do not.",
        preconditions="Telemetry path to the chosen sensor is reachable.",
        target_assets=["TT-101"],
        expected_evidence=["twin residual (persistent/sudden)", "energy-balance violation", "watermark unaffected"],
        params={"tag": "TT-101", "mode": "bias", "bias": -18.0, "target_value": 452.0, "ramp_s": 0.0})

    def on_start(self, t: float) -> None:
        s = self.ctx.sensors[self.params["tag"]]
        mode, bias, target, ramp = (self.params[k] for k in ("mode", "bias", "target_value", "ramp_s"))
        t0 = t

        def hook(_t: float, value: float) -> float:
            frac = 1.0 if ramp <= 0 else min(1.0, (_t - t0) / ramp)
            if mode == "freeze":
                return value  # handled by FrozenSensor; kept for completeness
            if mode == "setpoint":
                return value + frac * (target - value)
            return value + frac * bias  # bias

        s.output_hook = hook
        self.note(t, f"telemetry hook installed on {self.params['tag']} ({mode})")

    def on_stop(self, t: float) -> None:
        self.ctx.sensors[self.params["tag"]].output_hook = None


class FrozenSensor(Scenario):
    meta = ScenarioMeta(
        key="frozen_sensor", name="Frozen sensor readings", category="process_falsification",
        description="A sensor is held at its last value (loss of signal masked as a steady reading). The real "
                    "process keeps moving, so the twin residual and the stuck-at check diverge.",
        preconditions="Telemetry path to the chosen sensor is reachable.",
        target_assets=["FT-101"],
        expected_evidence=["frozen-value (stuck-at) check", "twin residual", "pump-flow inconsistency"],
        params={"tag": "FT-101"})

    def on_start(self, t: float) -> None:
        s = self.ctx.sensors[self.params["tag"]]
        held = {"v": None}

        def hook(_t: float, value: float) -> float:
            if held["v"] is None:
                held["v"] = value
            return held["v"]

        s.output_hook = hook

    def on_stop(self, t: float) -> None:
        self.ctx.sensors[self.params["tag"]].output_hook = None


class ActuatorResponseManipulation(Scenario):
    meta = ScenarioMeta(
        key="actuator_manipulation", name="Actuator response manipulation", category="actuator_falsification",
        description="Compromised final-element firmware ignores part of the command and reports the commanded "
                    "value back (deceptive feedback). The pump moves less than asked; flow disagrees with the "
                    "commanded speed.",
        preconditions="Field device firmware integrity cannot be assumed.",
        target_assets=["P-101"],
        expected_evidence=["pump-flow inconsistency", "twin residual", "energy-balance drift"],
        params={"actuator": "P-101", "scale": 0.7, "offset": 0.0, "report_command": True})

    def on_start(self, t: float) -> None:
        a = self.ctx.actuators[self.params["actuator"]]
        a.firmware_hook = {"scale": self.params["scale"], "offset": self.params["offset"],
                           "report_command": bool(self.params["report_command"])}

    def on_stop(self, t: float) -> None:
        self.ctx.actuators[self.params["actuator"]].firmware_hook = None


# ---------------------------------------------------------------------------
# Command-path scenarios: an unauthorized/rogue origin writes to a controller.
# The write is a genuine protocol message on the simulated network, so the
# network layer sees the evidence (source, allow-list, transaction ids).
# ---------------------------------------------------------------------------
class UnauthorizedSetpoint(Scenario):
    meta = ScenarioMeta(
        key="unauthorized_setpoint", name="Unauthorized setpoint modification", category="command_injection",
        description="A rogue device on the control LAN writes a holding register on a PLC without authorization. "
                    "SCADA keeps the operator-approved value, so the reported setpoint and the approved value "
                    "diverge.",
        preconditions="Rogue endpoint can reach the control switch; PLC write allow-list not yet enforced.",
        target_assets=["PLC-1"],
        expected_evidence=["unauthorized write (unknown source)", "setpoint deviation from approved value"],
        params={"plc": "PLC-1", "register": "TIC-101.SP", "value": 492.0, "period_s": 2.0, "source": "ATK-01"})

    def on_start(self, t: float) -> None:
        self._next = t
        topo = self.ctx.topology
        n = topo.nodes.get(self.params["source"])
        if n is not None:
            n.hidden = False  # the rogue device now appears on the topology view

    def on_tick(self, t: float, dt: float) -> None:
        if t < self._next:
            return
        self._next = t + self.params["period_s"]
        plc = self.params["plc"]
        m = self.ctx.register_maps[plc]
        reg = self.params["register"]
        if reg not in m["holding"]:
            return
        addr = m["holding"].index(reg) * 2
        raw = mb.encode_write_multiple(0x1000 + int(t) % 4096, m["unit"], addr,
                                       mb.floats_to_bytes([self.params["value"]]))
        self.ctx.bus.send(Message(t, self.params["source"], plc, "modbus_tcp",
                                  "FC16 Write Multiple Registers (request)",
                                  {"tid": 0x1000, "unit": m["unit"], "fc": 16, "addr": addr,
                                   "value": self.params["value"]}, raw=raw))

    def on_stop(self, t: float) -> None:
        self.ctx.lab_restore_setpoints(t)


class CommandReplay(Scenario):
    meta = ScenarioMeta(
        key="command_replay", name="Command replay", category="command_injection",
        description="A previously observed control write is captured passively, then re-sent verbatim. The "
                    "byte-identical frame (same transaction id) is replayed from a rogue origin.",
        preconditions="Attacker can observe traffic (SPAN/tap) and inject onto the control LAN.",
        target_assets=["PLC-1"],
        expected_evidence=["replayed-frame match", "unauthorized write", "setpoint deviation"],
        params={"plc": "PLC-1", "capture_register": "TIC-101.SP", "replay_period_s": 3.0, "source": "ATK-01",
                "capture_s": 6.0})

    def on_start(self, t: float) -> None:
        self._captured: Optional[bytes] = None
        self._next = None
        plc = self.params["plc"]

        def capture(msg: Message) -> None:
            if (self._captured is None and msg.protocol == "modbus_tcp" and msg.dst == plc
                    and msg.raw is not None and msg.kind.startswith("FC16")):
                self._captured = msg.raw
                self.note(msg.t_sent, "captured a legitimate control write for replay", tid=msg.payload.get("tid"))

        self._cap = capture
        self.ctx.bus.capture_taps.append(capture)
        n = self.ctx.topology.nodes.get(self.params["source"])
        if n is not None:
            n.hidden = False

    def on_tick(self, t: float, dt: float) -> None:
        if self._captured is None:
            return
        if self._next is None:
            self._next = t + 0.5
            self.note(t, "replay phase begins")
        if t < self._next:
            return
        self._next = t + self.params["replay_period_s"]
        adu = mb.decode_adu(self._captured, is_response=False)
        self.ctx.bus.send(Message(t, self.params["source"], self.params["plc"], "modbus_tcp",
                                  "FC16 Write Multiple Registers (request)",
                                  {"tid": adu.tid, "unit": adu.unit, "fc": 16, "replayed": True},
                                  raw=self._captured))

    def effect_active(self, t: float) -> bool:
        # Only the replay phase (after a frame has been captured and re-sent) is a positive label.
        return self.active and self._captured is not None and self._next is not None

    def on_stop(self, t: float) -> None:
        if self._cap in self.ctx.bus.capture_taps:
            self.ctx.bus.capture_taps.remove(self._cap)
        self.ctx.lab_restore_setpoints(t)


# ---------------------------------------------------------------------------
# Availability: controlled extra delay + loss on a link (simulated congestion).
# ---------------------------------------------------------------------------
class NetworkDoS(Scenario):
    meta = ScenarioMeta(
        key="network_dos", name="Supervisory link congestion (DoS)", category="availability",
        description="Extra latency, jitter and loss are applied to the supervisory uplink, plus a burst of junk "
                    "traffic from a rogue host, degrading SCADA polling of the controllers.",
        preconditions="Attacker can influence a shared network segment.",
        target_assets=["FW-01", "SW-SUP"],
        expected_evidence=["message-rate spike", "connection flood", "comm degradation / timeouts"],
        params={"link": ["SW-SUP", "FW-01"], "extra_delay_ms": 220.0, "extra_jitter_ms": 120.0,
                "extra_loss": 0.35, "flood_rate_hz": 400.0, "flood_source": "ATK-01", "flood_target": "SCADA-01"})

    def on_start(self, t: float) -> None:
        a, b = self.params["link"]
        self._link = self.ctx.topology.link(a, b)
        self._link.extra_delay_ms = self.params["extra_delay_ms"]
        self._link.extra_jitter_ms = self.params["extra_jitter_ms"]
        self._link.extra_loss = self.params["extra_loss"]
        self._link.suspicious = True
        self._next = t
        self._pkt = 0
        n = self.ctx.topology.nodes.get(self.params["flood_source"])
        if n is not None:
            n.hidden = False

    def on_tick(self, t: float, dt: float) -> None:
        rate = self.params["flood_rate_hz"]
        n = int(rate * dt)
        for _ in range(n):
            self._pkt += 1
            self.ctx.bus.send(Message(t, self.params["flood_source"], self.params["flood_target"], "modbus_tcp",
                                      "FC03 Read Holding Registers (request)",
                                      {"flood": True, "n": self._pkt},
                                      raw=mb.encode_read_request(self._pkt & 0xFFFF, 1, 3, 0, 2)))

    def on_stop(self, t: float) -> None:
        self._link.extra_delay_ms = 0.0
        self._link.extra_jitter_ms = 0.0
        self._link.extra_loss = 0.0
        self._link.suspicious = False


class InsiderMisuse(Scenario):
    meta = ScenarioMeta(
        key="insider_misuse", name="Out-of-policy engineering change", category="policy_violation",
        description="An engineering-workstation session writes an operational register outside an approved "
                    "maintenance window — a legitimate account used for an out-of-policy action.",
        preconditions="Engineering workstation has a valid session; no maintenance window is open.",
        target_assets=["PLC-1"],
        expected_evidence=["policy-violation write (EWS, operational register, no maintenance window)"],
        params={"plc": "PLC-1", "register": "P-101.SP", "value": 62.0, "user": "engineer1", "period_s": 3.0})

    def on_start(self, t: float) -> None:
        self.ctx.lab_login("EWS-01", self.params["user"], t)
        self._next = t + 0.5

    def on_tick(self, t: float, dt: float) -> None:
        if t < self._next:
            return
        self._next = t + self.params["period_s"]
        plc = self.params["plc"]
        m = self.ctx.register_maps[plc]
        reg = self.params["register"]
        addr = m["holding"].index(reg) * 2
        self.ctx.ews.modbus_write(t, plc, m["unit"], addr, self.params["value"])

    def on_stop(self, t: float) -> None:
        self.ctx.lab_logout("EWS-01", t)
        self.ctx.lab_restore_setpoints(t)


class TwinModelTamper(Scenario):
    meta = ScenarioMeta(
        key="twin_model_tamper", name="Digital-twin model parameter change", category="model_tampering",
        description="A write to the digital twin's configuration node changes a model parameter so the twin's "
                    "predictions drift away from a healthy plant — an attempt to blind the twin-based detector.",
        preconditions="Twin configuration endpoint reachable from the engineering workstation.",
        target_assets=["TWIN-01"],
        expected_evidence=["twin configuration change (network)", "model-confidence drop", "twin residual growth"],
        params={"node": "ns=3;s=Twin.HX.UA_SCALE", "value": 0.5, "user": "engineer1"})

    def on_start(self, t: float) -> None:
        self.ctx.lab_login("EWS-01", self.params["user"], t)
        self.ctx.ews.opcua_write(t + 0.2, "TWIN-01", self.params["node"], self.params["value"])
        self.note(t, "twin configuration write issued", node=self.params["node"], value=self.params["value"])

    def on_stop(self, t: float) -> None:
        # restore the design value and ask the twin to resynchronise
        self.ctx.ews.opcua_write(t, "TWIN-01", self.params["node"], 1.0)
        self.ctx.lab_logout("EWS-01", t)


class WatermarkInterference(Scenario):
    meta = ScenarioMeta(
        key="watermark_interference", name="Watermark observation interference", category="process_falsification",
        description="A stealthy replay smooths the flow/pressure telemetry around a slow-moving average, erasing "
                    "the small watermark signature while the mean reading still looks plausible.",
        preconditions="Attacker can rewrite watermarked-channel telemetry (FT-101 / PT-101).",
        target_assets=["FT-101", "PT-101"],
        expected_evidence=["missing/abnormal watermark response", "twin residual (if drift accumulates)"],
        params={"tags": ["FT-101", "PT-101"], "smoothing": 0.03})

    def on_start(self, t: float) -> None:
        self._avg: dict[str, Optional[float]] = {tag: None for tag in self.params["tags"]}
        a = self.params["smoothing"]
        for tag in self.params["tags"]:
            s = self.ctx.sensors[tag]

            def make(tag_: str):
                def hook(_t: float, value: float) -> float:
                    prev = self._avg[tag_]
                    self._avg[tag_] = value if prev is None else prev + a * (value - prev)
                    return self._avg[tag_]
                return hook

            s.output_hook = make(tag)

    def on_stop(self, t: float) -> None:
        for tag in self.params["tags"]:
            self.ctx.sensors[tag].output_hook = None


class CoordinatedAttack(Scenario):
    meta = ScenarioMeta(
        key="coordinated", name="Coordinated process + network anomaly", category="coordinated",
        description="A rogue setpoint write is combined with telemetry falsification that hides the resulting "
                    "process change — the multi-layer case where no single layer sees the whole picture.",
        preconditions="Rogue control-LAN endpoint plus a telemetry-rewrite capability.",
        target_assets=["PLC-1", "TT-101", "FT-101"],
        expected_evidence=["unauthorized write", "twin residual", "energy-balance violation", "correlated incident"],
        params={"plc": "PLC-1", "register": "TIC-101.SP", "value": 495.0, "mask_tag": "TT-101",
                "mask_value": 451.0, "period_s": 2.0, "source": "ATK-01"})

    def on_start(self, t: float) -> None:
        self._next = t + 0.5
        s = self.ctx.sensors[self.params["mask_tag"]]
        target = self.params["mask_value"]
        s.output_hook = lambda _t, value: target + 0.15 * (value - target)  # clamp reading near a benign value
        n = self.ctx.topology.nodes.get(self.params["source"])
        if n is not None:
            n.hidden = False

    def on_tick(self, t: float, dt: float) -> None:
        if t < self._next:
            return
        self._next = t + self.params["period_s"]
        plc = self.params["plc"]
        m = self.ctx.register_maps[plc]
        reg = self.params["register"]
        addr = m["holding"].index(reg) * 2
        raw = mb.encode_write_multiple(0x2000 + int(t) % 4096, m["unit"], addr,
                                       mb.floats_to_bytes([self.params["value"]]))
        self.ctx.bus.send(Message(t, self.params["source"], plc, "modbus_tcp",
                                  "FC16 Write Multiple Registers (request)",
                                  {"tid": 0x2000, "unit": m["unit"], "fc": 16, "addr": addr,
                                   "value": self.params["value"]}, raw=raw))

    def on_stop(self, t: float) -> None:
        self.ctx.sensors[self.params["mask_tag"]].output_hook = None
        self.ctx.lab_restore_setpoints(t)


SCENARIOS: dict[str, type[Scenario]] = {
    c.meta.key: c for c in (
        FalseDataInjection, FrozenSensor, ActuatorResponseManipulation, UnauthorizedSetpoint, CommandReplay,
        NetworkDoS, InsiderMisuse, TwinModelTamper, WatermarkInterference, CoordinatedAttack,
    )
}


def catalog() -> list[dict]:
    out = []
    for key, cls in SCENARIOS.items():
        m = cls.meta
        out.append({"key": key, "name": m.name, "category": m.category, "description": m.description,
                    "preconditions": m.preconditions, "target_assets": m.target_assets,
                    "expected_evidence": m.expected_evidence, "default_params": m.params})
    return out
