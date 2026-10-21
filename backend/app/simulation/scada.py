"""Supervisory layer: SCADA server, HMI / engineering workstations, historian,
MQTT broker and authentication server.

The SCADA server only learns plant values through protocol messages (Modbus
responses it decodes, MQTT publishes from the broker).  It holds the
*operator-approved* setpoints, which the IDS compares against what the PLCs
report back.
"""
from __future__ import annotations

from collections import deque
from typing import Optional

from app.network import protocols as mb
from app.network.traffic import Message, NetworkBus
from app.simulation.devices import DeviceRegistry, Sensor

ROLE_PERMISSIONS = {
    "operator": {"operational"},
    "engineer": {"operational", "config"},
    "contractor": set(),
    "service": {"system"},
}

USERS = {
    "operator1": {"role": "operator", "name": "Control-room operator", "enabled": True},
    "engineer1": {"role": "engineer", "name": "Control-systems engineer", "enabled": True},
    "contractor1": {"role": "contractor", "name": "Maintenance contractor (read-only)", "enabled": True},
    "scada-svc": {"role": "service", "name": "SCADA service account", "enabled": True},
}

# SCADA-level operating envelope for operator setpoints (narrower than PLC engineering ranges)
OPERATING_ENVELOPE = {
    "TIC-101.SP": (380.0, 500.0), "P-101.SP": (50.0, 100.0), "FCV-101.SP": (30.0, 100.0),
    "TIC-101.MODE": (0, 1), "HTR-101.MAN": (0, 100),
    "TIC-201.SP": (200.0, 240.0), "P-201.SP": (50.0, 100.0),
    "LIC-302.SP": (2.0, 5.0), "AIC-302.SP": (0.5, 2.0),
    "TIC-401.SP": (30.0, 60.0), "BATCH.ENABLE": (0, 1),
    "FIC-501.SP": (40.0, 110.0),
    "TIC-101.KP": (0.5, 10), "TIC-101.TI": (10, 300), "TIC-201.KP": (0.5, 20), "TIC-201.TI": (10, 300),
    "BW.DP_SP": (0.5, 1.1), "BW.DURATION": (20, 90), "BATCH.REACT_S": (20, 300),
    "ROUTE.HI": (6, 9.2), "ROUTE.LO": (1, 3),
}


class IdentityService:
    """AUTH-01: users, roles and workstation sessions (simulated directory service)."""

    def __init__(self) -> None:
        self.users = {k: dict(v) for k, v in USERS.items()}
        self.sessions: dict[str, str] = {"HMI-01": "operator1", "SCADA-01": "scada-svc"}
        self.log: deque[dict] = deque(maxlen=200)

    def role(self, user: Optional[str]) -> Optional[str]:
        u = self.users.get(user or "")
        return u["role"] if u else None

    def can_write(self, user: Optional[str], category: str) -> bool:
        u = self.users.get(user or "")
        return bool(u and u["enabled"] and category in ROLE_PERMISSIONS.get(u["role"], set()))

    def login(self, node: str, user: str, t: float) -> bool:
        u = self.users.get(user)
        ok = bool(u and u["enabled"])
        if ok:
            self.sessions[node] = user
        self.log.append({"t": round(t, 2), "node": node, "user": user, "event": "login", "ok": ok})
        return ok

    def logout(self, node: str, t: float) -> None:
        user = self.sessions.pop(node, None)
        self.log.append({"t": round(t, 2), "node": node, "user": user, "event": "logout", "ok": True})

    def disable(self, user: str, t: float) -> list[str]:
        if user in self.users:
            self.users[user]["enabled"] = False
        revoked = [n for n, u in self.sessions.items() if u == user]
        for n in revoked:
            del self.sessions[n]
        self.log.append({"t": round(t, 2), "user": user, "event": "disabled", "revoked": revoked, "ok": True})
        return revoked

    def to_dict(self) -> dict:
        return {"users": [{"user": k, **v} for k, v in self.users.items()], "sessions": dict(self.sessions),
                "log": list(self.log)[-20:]}


class AuthServer:
    def __init__(self, bus: NetworkBus, identity: IdentityService):
        self.bus, self.identity = bus, identity
        bus.register("AUTH-01", self.on_message)

    def on_message(self, msg: Message) -> None:
        if msg.protocol != "auth":
            return
        p = msg.payload
        ok = self.identity.login(msg.src, p.get("user", ""), msg.t_deliver)
        self.bus.send(Message(msg.t_deliver + 0.001, "AUTH-01", msg.src, "auth", "AS-REP",
                              {"service": "AS-REP", "user": p.get("user"), "result": "success" if ok else "denied"},
                              user=p.get("user")))


class MqttBroker:
    def __init__(self, bus: NetworkBus):
        self.bus = bus
        self.subscriptions = {"site/tankfarm/RTU-5/telemetry": ["SCADA-01"], "site/tankfarm/RTU-5/cmd": ["RTU-5"]}
        self.forwarded = 0
        bus.register("MQTT-01", self.on_message)

    def on_message(self, msg: Message) -> None:
        if msg.protocol != "mqtt":
            return
        topic = msg.payload.get("topic", "")
        for sub in self.subscriptions.get(topic, []):
            self.forwarded += 1
            self.bus.send(Message(msg.t_deliver + 0.0005, "MQTT-01", sub, "mqtt", msg.kind, msg.payload,
                                  user=msg.user, seq=msg.seq))


class Historian:
    def __init__(self, bus: NetworkBus):
        self.samples = 0
        self.last: dict[str, float] = {}
        bus.register("HIST-01", self.on_message)

    def on_message(self, msg: Message) -> None:
        if msg.payload.get("service") == "PublishResponse":
            for item in msg.payload["notificationMessage"]["dataChangeNotification"]:
                self.last[item["nodeId"]] = item["value"]
                self.samples += 1


class Workstation:
    """HMI-01 / EWS-01: originate operator / engineering traffic."""

    def __init__(self, node_id: str, bus: NetworkBus, identity: IdentityService):
        self.id, self.bus, self.identity = node_id, bus, identity
        self.handle = 0
        self.tid = 4000 if node_id == "EWS-01" else 0
        self.responses: deque[dict] = deque(maxlen=50)
        bus.register(node_id, self.on_message)

    @property
    def user(self) -> Optional[str]:
        return self.identity.sessions.get(self.id)

    def on_message(self, msg: Message) -> None:
        self.responses.append({"t": msg.t_deliver, "kind": msg.kind, "payload": msg.payload})

    def login(self, t: float, user: str) -> None:
        self.bus.send(Message(t, self.id, "AUTH-01", "auth", "AS-REQ",
                              {"service": "AS-REQ (emulated)", "user": user, "workstation": self.id}, user=user))

    def opcua_write(self, t: float, dst: str, node_id: str, value) -> None:
        self.handle += 1
        self.bus.send(Message(t, self.id, dst, "opcua", "WriteRequest",
                              mb.opcua_write_request(self.handle, node_id, value), user=self.user, seq=self.handle))

    def modbus_write(self, t: float, plc_id: str, unit: int, addr: int, value: float) -> Optional[Message]:
        if self.user is None:
            return None  # no authenticated session on this workstation
        self.tid = (self.tid + 1) & 0xFFFF
        raw = mb.encode_write_multiple(self.tid, unit, addr, mb.floats_to_bytes([value]))
        return self.bus.send(Message(t, self.id, plc_id, "modbus_tcp", "FC16 Write Multiple Registers (request)",
                                     {"tid": self.tid, "unit": unit, "fc": 16, "addr": addr, "value": value},
                                     raw=raw, user=self.user))

    def modbus_read(self, t: float, plc_id: str, unit: int, fc: int, addr: int, count: int) -> None:
        self.tid = (self.tid + 1) & 0xFFFF
        raw = mb.encode_read_request(self.tid, unit, fc, addr, count)
        self.bus.send(Message(t, self.id, plc_id, "modbus_tcp", f"FC{fc:02d} {mb.FC_NAMES.get(fc, '')} (request)",
                              {"tid": self.tid, "unit": unit, "fc": fc, "addr": addr, "count": count}, raw=raw,
                              user=self.user))


class ScadaServer:
    POLL = {"PLC-1": (0.1, 0.5), "PLC-2": (0.1, 0.5), "PLC-3": (0.5, 1.0), "PLC-4": (0.5, 1.0)}
    TIMEOUT = 1.0

    def __init__(self, bus: NetworkBus, register_maps: dict[str, dict], registry: DeviceRegistry,
                 identity: IdentityService):
        self.bus = bus
        self.maps = register_maps  # plc -> {"unit", "inputs": [names], "holding": [names], "category": {name: cat}}
        self.registry = registry
        self.identity = identity
        self.tags: dict[str, list] = {}  # tag -> [value, t, plc]
        self.approved: dict[str, float] = {}
        self.approved_by: dict[str, dict] = {}
        self.tag_plc: dict[str, str] = {}
        self.next_poll: dict[tuple[str, int], float] = {}
        self.tid: dict[str, int] = {p: 0 for p in self.POLL}
        self.pending: dict[tuple[str, int], tuple[float, int, int, int]] = {}
        self.last_resp: dict[str, float] = {p: 0.0 for p in list(self.POLL) + ["RTU-5"]}
        self.rtt: dict[str, deque] = {p: deque(maxlen=50) for p in self.POLL}
        self.timeouts: dict[str, deque] = {p: deque(maxlen=100) for p in self.POLL}
        self.exceptions: deque[dict] = deque(maxlen=100)
        self.unsolicited = 0
        self.alarms: dict[str, dict] = {}
        self.alarm_events: list[dict] = []
        self.write_log: deque[dict] = deque(maxlen=200)
        self.sub_seq = 0
        self.mqtt_pkt = 0
        self.ua_handle = 0
        self._last_hb = -10.0
        self._last_hist = -10.0
        self._last_twin = -10.0
        for plc, m in self.maps.items():
            for n in m["inputs"]:
                self.tag_plc[n] = plc
            for n in m["holding"]:
                if n != "HEARTBEAT":
                    self.tag_plc[n] = plc
            for n, v in m.get("initial_holding", {}).items():
                if m["category"].get(n) in ("operational", "config"):
                    self.approved[n] = v
        bus.register("SCADA-01", self.on_message)

    # ------------------------------------------------------------------ data access
    def value(self, tag: str, default: float = float("nan")) -> float:
        e = self.tags.get(tag)
        return e[0] if e else default

    def age(self, tag: str, now: float) -> float:
        e = self.tags.get(tag)
        return now - e[1] if e else 1e9

    def quality(self, tag: str, now: float) -> str:
        a = self.age(tag, now)
        plc = self.tag_plc.get(tag, "")
        period = self.POLL.get(plc, (0.5, 1.0))[0]
        if a <= 3 * period + 0.35:
            return "good"
        if a <= 5.0:
            return "stale"
        return "bad"

    # ------------------------------------------------------------------ periodic work
    def tick(self, t: float) -> None:
        for plc, (p_in, p_hold) in self.POLL.items():
            for fc, period in ((4, p_in), (3, p_hold)):
                key = (plc, fc)
                if t + 1e-9 >= self.next_poll.get(key, 0.0):
                    self.next_poll[key] = t + period
                    self._poll(t, plc, fc)
        # timeouts
        for (plc, tid), (ts, fc, addr, cnt) in list(self.pending.items()):
            if t - ts > self.TIMEOUT:
                del self.pending[(plc, tid)]
                self.timeouts[plc].append(t)
        if t - self._last_hb >= 1.0:
            self._last_hb = t
            for plc, m in self.maps.items():
                if plc in self.POLL:
                    addr = m["holding"].index("HEARTBEAT") * 2
                    self._write_raw(t + 0.004, plc, addr, float(int(t) % 60000), user="scada-svc")
        if t - self._last_hist >= 1.0:
            self._last_hist = t
            items = [(f"ns=2;s={k}", v[0], v[1]) for k, v in list(self.tags.items())[:40]]
            self.sub_seq += 1
            self.bus.send(Message(t + 0.006, "SCADA-01", "HIST-01", "opcua", "PublishResponse",
                                  mb.opcua_publish_response(1, self.sub_seq, items), seq=self.sub_seq))
        if t - self._last_twin >= 0.5:
            self._last_twin = t
            keys = ("TT-101", "TT-102", "TT-103", "FT-101", "PT-101", "PT-102", "JT-101", "TT-201", "TT-202",
                    "FT-201", "JT-201")
            items = [(f"ns=2;s={k}", self.tags[k][0], self.tags[k][1]) for k in keys if k in self.tags]
            self.sub_seq += 1
            self.bus.send(Message(t + 0.007, "SCADA-01", "TWIN-01", "opcua", "PublishResponse",
                                  mb.opcua_publish_response(2, self.sub_seq, items), seq=self.sub_seq))

    def _poll(self, t: float, plc: str, fc: int) -> None:
        m = self.maps[plc]
        names = m["inputs"] if fc == 4 else m["holding"]
        self.tid[plc] = (self.tid[plc] + 1) & 0xFFFF
        tid = self.tid[plc]
        count = 2 * len(names)
        raw = mb.encode_read_request(tid, m["unit"], fc, 0, count)
        self.pending[(plc, tid)] = (t, fc, 0, count)
        self.bus.send(Message(t + 0.005, "SCADA-01", plc, "modbus_tcp", f"FC{fc:02d} {mb.FC_NAMES[fc]} (request)",
                              {"tid": tid, "unit": m["unit"], "fc": fc, "addr": 0, "count": count}, raw=raw))

    def _write_raw(self, t: float, plc: str, addr: int, value: float, user: str) -> int:
        m = self.maps[plc]
        self.tid[plc] = (self.tid[plc] + 1) & 0xFFFF
        tid = self.tid[plc]
        raw = mb.encode_write_multiple(tid, m["unit"], addr, mb.floats_to_bytes([value]))
        self.pending[(plc, tid)] = (t, 16, addr, 2)
        self.bus.send(Message(t, "SCADA-01", plc, "modbus_tcp", "FC16 Write Multiple Registers (request)",
                              {"tid": tid, "unit": m["unit"], "fc": 16, "addr": addr, "value": round(value, 4)},
                              raw=raw, user=user))
        return tid

    # ------------------------------------------------------------------ operator commands
    def category(self, plc: str, reg: str) -> Optional[str]:
        return self.maps.get(plc, {}).get("category", {}).get(reg)

    def validate_write(self, plc: str, reg: str, value: float, user: Optional[str],
                       trusted: bool = False) -> Optional[str]:
        if plc not in self.maps:
            return f"unknown controller {plc}"
        cat = self.category(plc, reg)
        if cat is None or reg == "HEARTBEAT":
            return f"register {reg} is not writable on {plc}"
        if not trusted and not self.identity.can_write(user, cat):
            return f"user {user} (role {self.identity.role(user)}) may not write {cat} registers"
        env = OPERATING_ENVELOPE.get(reg)
        if env and not (env[0] <= value <= env[1]):
            return f"{reg}={value} outside operating envelope [{env[0]}, {env[1]}]"
        return None

    def write_setpoint(self, t: float, plc: str, reg: str, value: float, user: str, approve: bool = True,
                       trusted: bool = False) -> dict:
        err = self.validate_write(plc, reg, value, user, trusted=trusted)
        rec = {"t": round(t, 3), "plc": plc, "register": reg, "value": value, "user": user, "accepted": err is None,
               "reason": err}
        self.write_log.append(rec)
        if err:
            return rec
        if approve:
            self.approved[reg] = value
            self.approved_by[reg] = {"user": user, "t": round(t, 3)}
        if plc == "RTU-5":
            self.mqtt_pkt = (self.mqtt_pkt % 65535) + 1
            self.bus.send(Message(t + 0.002, "SCADA-01", "MQTT-01", "mqtt", "PUBLISH command",
                                  mb.mqtt_publish("site/tankfarm/RTU-5/cmd", self.mqtt_pkt,
                                                  {"register": reg, "value": value}), user=user, seq=self.mqtt_pkt))
        else:
            addr = self.maps[plc]["holding"].index(reg) * 2
            rec["tid"] = self._write_raw(t + 0.002, plc, addr, value, user)
        return rec

    # ------------------------------------------------------------------ message handling
    def on_message(self, msg: Message) -> None:
        if msg.protocol == "modbus_tcp" and msg.raw is not None:
            self._on_modbus(msg)
        elif msg.protocol == "mqtt":
            body = msg.payload.get("payload", {})
            if msg.payload.get("topic", "").endswith("/telemetry"):
                for k, v in body.items():
                    if k.startswith("SP:"):
                        self.tags[k[3:]] = [v, msg.t_deliver, "RTU-5"]
                        self.tag_plc[k[3:]] = "RTU-5"
                    else:
                        self.tags[k] = [v, msg.t_deliver, "RTU-5"]
                        self.tag_plc[k] = "RTU-5"
                self.last_resp["RTU-5"] = msg.t_deliver
        elif msg.protocol == "opcua" and msg.payload.get("service") == "WriteRequest":
            node = msg.payload["nodesToWrite"][0]
            nid, val = node["nodeId"], node["value"]
            try:
                plc, reg = nid.split(";s=", 1)[1].split(".", 1)
            except (IndexError, ValueError):
                plc, reg = "?", nid
            rec = self.write_setpoint(msg.t_deliver, plc, reg, float(val), msg.user or "")
            self.bus.send(Message(msg.t_deliver + 0.001, "SCADA-01", msg.src, "opcua", "WriteResponse",
                                  mb.opcua_write_response(msg.payload["requestHandle"],
                                                          "Good" if rec["accepted"] else "BadUserAccessDenied"),
                                  seq=msg.seq))

    def _on_modbus(self, msg: Message) -> None:
        try:
            adu = mb.decode_adu(msg.raw, is_response=True)
        except mb.ModbusDecodeError:
            return
        plc = msg.src
        req = self.pending.pop((plc, adu.tid), None)
        if req is None:
            self.unsolicited += 1
            return
        t_sent, fc, addr, cnt = req
        self.rtt.setdefault(plc, deque(maxlen=50)).append(msg.t_deliver - t_sent)
        self.last_resp[plc] = msg.t_deliver
        if adu.is_exception:
            self.exceptions.append({"t": msg.t_deliver, "plc": plc, "fc": adu.fc, "code": adu.exception_code})
            return
        if fc in (3, 4):
            names = self.maps[plc]["inputs" if fc == 4 else "holding"][addr // 2: (addr + cnt) // 2]
            vals = mb.bytes_to_floats(adu.data)
            t = msg.t_deliver
            for n, v in zip(names, vals):
                if n != "HEARTBEAT":
                    self.tags[n] = [v, t, plc]

    # ------------------------------------------------------------------ HMI alarms / comm status
    def evaluate(self, t: float) -> list[dict]:
        new_events = []
        for s in self.registry.sensors:
            e = self.tags.get(s.id)
            if not e:
                continue
            lvl = s.limits.classify(e[0])
            s.alarm_state = lvl
            prev = self.alarms.get(s.id)
            if lvl != "normal" and (prev is None or prev["level"] != lvl):
                self.alarms[s.id] = {"tag": s.id, "level": lvl, "value": round(e[0], 3), "since": round(t, 2)}
                new_events.append({"t": t, "tag": s.id, "level": lvl, "value": e[0]})
            elif lvl == "normal" and prev is not None:
                del self.alarms[s.id]
                new_events.append({"t": t, "tag": s.id, "level": "cleared", "value": e[0]})
        for plc in list(self.POLL) + ["RTU-5"]:
            age = t - self.last_resp.get(plc, 0.0)
            dev = self.registry.devices.get(plc)
            if dev is not None and not dev.quarantined:
                dev.comm_status = "online" if age < 1.0 else "degraded" if age < 5.0 else "offline"
        self.alarm_events.extend(new_events)
        return new_events

    def comm_quality(self, plc: str, t: float, window: float = 5.0) -> dict:
        rtts = list(self.rtt.get(plc, []))[-20:]
        tos = [x for x in self.timeouts.get(plc, []) if t - x <= window]
        return {"rtt_ms": round(1000 * sum(rtts) / len(rtts), 2) if rtts else None,
                "rtt_max_ms": round(1000 * max(rtts), 2) if rtts else None,
                "timeouts_5s": len(tos), "age_s": round(t - self.last_resp.get(plc, 0.0), 2)}

    def to_dict(self, t: float) -> dict:
        return {
            "approved_setpoints": dict(self.approved),
            "approved_by": dict(self.approved_by),
            "alarms": list(self.alarms.values()),
            "comm": {p: self.comm_quality(p, t) for p in list(self.POLL)},
            "write_log": list(self.write_log)[-20:],
            "unsolicited_responses": self.unsolicited,
            "exceptions": list(self.exceptions)[-10:],
        }
