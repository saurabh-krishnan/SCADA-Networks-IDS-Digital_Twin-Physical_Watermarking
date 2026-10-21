"""Generic PLC / RTU runtime with a Modbus TCP server and field I/O.

Register model: every value is an IEEE-754 float32 spread over two 16-bit
registers (big-endian word order).  Input registers (FC04) expose sensor values,
actuator commands/feedback and status words; holding registers (FC03/FC16)
expose setpoints, modes and configuration.

Like most real Modbus devices the PLC accepts writes from any source unless the
(simulated) write allow-list is enabled by the response engine.  It *does*
enforce engineering ranges on writes (exception 0x03), which an attacker can
stay inside of.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from app.network import protocols as mb
from app.network.traffic import Message
from app.simulation.control import PID


@dataclass
class HoldingSpec:
    name: str
    init: float
    lo: float
    hi: float
    unit: str = ""
    desc: str = ""
    category: str = "operational"  # operational | config | system


class RegisterBank:
    def __init__(self, names: list[str]):
        self.names = list(names)
        self.addr = {n: 2 * i for i, n in enumerate(self.names)}
        self.by_addr = {2 * i: n for i, n in enumerate(self.names)}
        self.values: dict[str, float] = {n: 0.0 for n in self.names}

    @property
    def n_regs(self) -> int:
        return 2 * len(self.names)

    def read_bytes(self, addr: int, count: int) -> Optional[bytes]:
        if addr % 2 or count % 2 or addr < 0 or addr + count > self.n_regs or count == 0 or count > 125:
            return None
        names = [self.by_addr[a] for a in range(addr, addr + count, 2)]
        return mb.floats_to_bytes([self.values[n] for n in names])

    def decode_write(self, addr: int, data: bytes) -> Optional[list[tuple[str, float]]]:
        count = len(data) // 2
        if addr % 2 or count % 2 or addr < 0 or addr + count > self.n_regs or count == 0:
            return None
        vals = mb.bytes_to_floats(data)
        return [(self.by_addr[addr + 2 * i], v) for i, v in enumerate(vals)]

    def table(self) -> list[dict]:
        return [{"address": self.addr[n], "name": n, "value": round(self.values[n], 4)} for n in self.names]


class PLC:
    def __init__(self, plc_id: str, name: str, unit_id: int, subsystem: str, sensors: list[str],
                 actuators: list[str], holding: list[HoldingSpec], extra_inputs: list[str],
                 program: Callable[["PLC", float, float], None], protocol: str = "modbus_tcp"):
        self.id = plc_id
        self.name = name
        self.unit_id = unit_id
        self.subsystem = subsystem
        self.sensor_ids = sensors
        self.actuator_ids = actuators
        self.protocol = protocol
        self.holding_spec = {h.name: h for h in holding}
        self.hold = RegisterBank([h.name for h in holding])
        for h in holding:
            self.hold.values[h.name] = h.init
        input_names = list(sensors)
        for a in actuators:
            input_names += [f"{a}.CMD", f"{a}.FB"]
        input_names += extra_inputs
        self.inp = RegisterBank(input_names)
        self.program = program
        self.field: dict[str, float] = {}
        self.field_t: dict[str, float] = {}
        self.fb: dict[str, float] = {}
        self.cmd: dict[str, float] = {}
        self.reported_cmd: dict[str, float] = {}
        self._last_sent: dict[str, tuple[float, float]] = {}
        self.pid: dict[str, PID] = {}
        self.state: dict[str, float] = {}
        self.di: dict[str, float] = {"SIS.TRIP": 0.0}
        self.bus = None
        self.t = 0.0
        self.allowlist_enforced = False
        self.allowed_writers = {"SCADA-01", "EWS-01"}
        self.write_log: deque[dict] = deque(maxlen=200)
        self.rejected_writes = 0
        self.last_heartbeat_t = 0.0
        self.watermark_hook: Optional[Callable[[str, float, float], float]] = None
        self.events: list[dict] = []
        self.scan_count = 0

    # ---------------------------------------------------------------- helpers
    def h(self, name: str) -> float:
        return self.hold.values[name]

    def sensor(self, sid: str, default: float = 0.0) -> float:
        return self.field.get(sid, default)

    def command(self, act: str, value: float, reported: Optional[float] = None) -> None:
        self.cmd[act] = value
        self.reported_cmd[act] = value if reported is None else reported

    # ---------------------------------------------------------------- network
    def on_message(self, msg: Message) -> None:
        if msg.protocol == "field":
            p = msg.payload
            if msg.kind == "AI_REPORT":
                self.field[p["tag"]] = p["value"]
                self.field_t[p["tag"]] = msg.t_deliver
            elif msg.kind == "AO_STATUS":
                self.fb[p["tag"]] = p["feedback"]
        elif msg.protocol == "modbus_tcp" and msg.raw is not None:
            resp = self.process_modbus(msg.raw, msg.src, msg.user, msg.t_deliver)
            if resp is not None and self.bus is not None:
                adu = mb.decode_adu(resp, is_response=True)
                self.bus.send(Message(msg.t_deliver + 0.0005, self.id, msg.src, "modbus_tcp",
                                      adu.describe("response"), {"tid": adu.tid, "unit": adu.unit, "fc": adu.fc,
                                                                 "exception": adu.exception_code}, raw=resp))
        elif msg.protocol == "mqtt":
            self.on_mqtt(msg)

    def on_mqtt(self, msg: Message) -> None:  # overridden by RTU
        pass

    def process_modbus(self, raw: bytes, src: str, user: Optional[str], t: float) -> Optional[bytes]:
        try:
            req = mb.decode_adu(raw, is_response=False)
        except mb.ModbusDecodeError as exc:
            self.events.append({"t": t, "type": "malformed_frame", "src": src, "detail": str(exc)})
            return None
        if req.unit not in (self.unit_id, 0, 255):
            return mb.encode_exception(req.tid, req.unit, req.fc, mb.EX_ILLEGAL_ADDRESS)
        fc = req.fc
        if fc in (3, 4):
            bank = self.hold if fc == 3 else self.inp
            data = bank.read_bytes(req.addr or 0, req.count or 0)
            if data is None:
                return mb.encode_exception(req.tid, req.unit, fc, mb.EX_ILLEGAL_ADDRESS)
            return mb.encode_read_response(req.tid, req.unit, fc, data)
        if fc == 16:
            if self.allowlist_enforced and src not in self.allowed_writers:
                self.rejected_writes += 1
                self.write_log.append({"t": t, "src": src, "user": user, "accepted": False, "reason": "allow-list"})
                self.events.append({"t": t, "type": "write_rejected", "src": src, "reason": "allow-list"})
                return mb.encode_exception(req.tid, req.unit, fc, mb.EX_ILLEGAL_FUNCTION)
            writes = self.hold.decode_write(req.addr or 0, req.data)
            if writes is None:
                return mb.encode_exception(req.tid, req.unit, fc, mb.EX_ILLEGAL_ADDRESS)
            for name, v in writes:
                spec = self.holding_spec[name]
                if not (spec.lo <= v <= spec.hi) or v != v:
                    self.write_log.append({"t": t, "src": src, "user": user, "register": name, "value": v,
                                           "accepted": False, "reason": "out of engineering range"})
                    return mb.encode_exception(req.tid, req.unit, fc, mb.EX_ILLEGAL_VALUE)
            for name, v in writes:
                old = self.hold.values[name]
                self.hold.values[name] = v
                if name == "HEARTBEAT":
                    self.last_heartbeat_t = t
                else:
                    self.write_log.append({"t": t, "src": src, "user": user, "register": name, "old": old,
                                           "value": v, "accepted": True})
            return mb.encode_write_multiple_response(req.tid, req.unit, req.addr or 0, req.count or 0)
        return mb.encode_exception(req.tid, req.unit, fc, mb.EX_ILLEGAL_FUNCTION)

    # ---------------------------------------------------------------- scan
    def scan(self, t: float, dt: float) -> None:
        self.t = t
        self.scan_count += 1
        self.program(self, t, dt)
        iv = self.inp.values
        for sid in self.sensor_ids:
            if sid in self.field:
                iv[sid] = self.field[sid]
        for a in self.actuator_ids:
            iv[f"{a}.CMD"] = self.reported_cmd.get(a, self.cmd.get(a, 0.0))
            iv[f"{a}.FB"] = self.fb.get(a, 0.0)
        if "STATUS.SIS_TRIP" in iv:
            iv["STATUS.SIS_TRIP"] = self.di.get("SIS.TRIP", 0.0)
        if "STATUS.WATCHDOG" in iv:
            iv["STATUS.WATCHDOG"] = 1.0 if (t - self.last_heartbeat_t) > 10.0 else 0.0
        for k, v in self.state.items():
            if k in iv:
                iv[k] = v
        if self.bus is None:
            return
        for a, v in self.cmd.items():
            last = self._last_sent.get(a)
            if last is None or abs(last[0] - v) > 0.01 or t - last[1] >= 1.0:
                self._last_sent[a] = (v, t)
                self.bus.send(Message(t + 0.0002, self.id, a, "field", "AO_WRITE", {"tag": a, "value": round(v, 4)}))

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "unit_id": self.unit_id, "subsystem": self.subsystem,
            "protocol": self.protocol, "allowlist_enforced": self.allowlist_enforced,
            "allowed_writers": sorted(self.allowed_writers), "rejected_writes": self.rejected_writes,
            "holding": [dict(r, **{"lo": self.holding_spec[r["name"]].lo, "hi": self.holding_spec[r["name"]].hi,
                                   "unit": self.holding_spec[r["name"]].unit,
                                   "category": self.holding_spec[r["name"]].category})
                        for r in self.hold.table()],
            "inputs": self.inp.table(),
            "state": {k: round(v, 3) for k, v in self.state.items()},
            "recent_writes": list(self.write_log)[-15:],
        }
