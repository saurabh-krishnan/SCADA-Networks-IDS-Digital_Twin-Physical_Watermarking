"""Network-layer detection on the SPAN copy of L1/L2 traffic.

Rules are transparent and configuration-driven (asset inventory, allowed flows,
authorised writers, register maps, operating envelope, maintenance window).
Only ``Mirror`` records are consumed — never simulator ground truth.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Optional

from app.ids.base import Condition
from app.network import protocols as mb
from app.network.traffic import Mirror

REC_QUARANTINE = "Quarantine the offending endpoint; preserve evidence"
REC_REJECT = "Enable PLC write allow-list (reject unauthorized commands); restore approved setpoint"
REC_USER = "Disable the user account; restore approved setpoints; review EWS session"
REC_DOS = "Fail over to redundant/secure channel; rate-limit or quarantine the source"


class NetworkDetector:
    LAYER = "network"

    def __init__(self, inventory: dict[str, dict], allowed_flows: set[tuple[str, str, str]],
                 authorized_writers: dict[str, set[str]], register_maps: dict[str, dict],
                 envelope: dict[str, tuple[float, float]], user_roles: dict[str, str], policy: dict,
                 learning_s: float = 20.0):
        self.inventory = inventory  # node -> {"ip", "mac", "kind"}
        self.ip_owner = {v["ip"]: k for k, v in inventory.items() if v.get("ip")}
        self.allowed = allowed_flows
        self.writers = authorized_writers
        self.maps = register_maps
        self.envelope = envelope
        self.user_roles = user_roles
        self.policy = policy
        self.learning_s = learning_s
        self.queue: list[Mirror] = []
        self.sessions: dict[str, str] = {"HMI-01": "operator1"}
        self.bucket: dict[tuple[str, str], int] = defaultdict(int)
        self.dst_bucket: dict[str, int] = defaultdict(int)
        self.rates: dict[tuple[str, str], float] = {}
        self.baseline: dict[tuple[str, str], float] = {}
        self._learn: dict[tuple[str, str], list[float]] = defaultdict(list)
        self.rate_high_since: dict[tuple[str, str], float] = {}
        self.last_bucket_t = 0.0
        self.seen_writes: dict[bytes, float] = {}
        self.last_tid: dict[tuple[str, str], int] = {}
        self.pending: dict[tuple[str, str, int], float] = {}
        self.rtt: dict[str, deque] = defaultdict(lambda: deque(maxlen=40))
        self.unanswered: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self.answered: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self.exceptions: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.integrity_events: list[dict] = []
        self.labels: dict[int, str] = {}  # msg id -> label for the UI
        self.stats = {"inspected": 0, "modbus_writes": 0, "flagged": 0}
        self.t0: Optional[float] = None

    def on_mirror(self, m: Mirror) -> None:
        self.queue.append(m)

    def on_bus_event(self, ev: dict) -> None:
        if ev.get("type") == "integrity_failure":
            self.integrity_events.append(ev)

    # ------------------------------------------------------------------ main
    def process(self, t: float) -> list[Condition]:
        if self.t0 is None:
            self.t0 = t
        out: list[Condition] = []
        q, self.queue = self.queue, []
        for m in q:
            self.stats["inspected"] += 1
            self.bucket[(m.src, m.dst)] += 1
            self.dst_bucket[m.dst] += 1
            conds = self._inspect(m)
            if conds:
                self.stats["flagged"] += 1
                self.labels[m.msg_id] = conds[0].category
                out.extend(conds)
        for ev in self.integrity_events:
            out.append(Condition(self.LAYER, "NET-INTEGRITY", ev["src"], "high", "Message tampering detected",
                                 {"detail": "secure-channel MAC verification failed at receiver", **ev}, 1.0, 0.9,
                                 "Investigate path between endpoints for a man-in-the-middle; keep secure channel",
                                 hold_s=20.0))
        self.integrity_events = []
        if t - self.last_bucket_t >= 1.0:
            out.extend(self._periodic(t, t - self.last_bucket_t))
            self.last_bucket_t = t
        if len(self.labels) > 3000:
            for k in list(self.labels)[:1500]:
                del self.labels[k]
        return out

    # ------------------------------------------------------------------ per-message rules
    def _inspect(self, m: Mirror) -> list[Condition]:
        out: list[Condition] = []
        inv = self.inventory.get(m.src)
        if inv is None:
            out.append(Condition(self.LAYER, "NET-UNKNOWN-DEVICE", m.src, "high", "Unexpected device connection",
                                 {"src": m.src, "dst": m.dst, "protocol": m.protocol, "kind": m.kind,
                                  "mac": m.src_mac, "detail": "source not in asset inventory"}, 1.0, 0.85,
                                 REC_QUARANTINE, hold_s=15.0))
        elif inv.get("mac") and m.src_mac and m.src_mac != inv["mac"]:
            out.append(Condition(self.LAYER, "NET-MAC-MISMATCH", m.src, "high", "Address spoofing / MITM indicator",
                                 {"src": m.src, "expected_mac": inv["mac"], "observed_mac": m.src_mac,
                                  "dst": m.dst, "kind": m.kind}, 1.0, 0.85, REC_QUARANTINE, hold_s=20.0))
        if m.protocol == "arp":
            claimed = m.payload.get("ip")
            owner = self.ip_owner.get(claimed)
            if owner and self.inventory[owner].get("mac") != m.payload.get("mac"):
                out.append(Condition(self.LAYER, "NET-ARP-SPOOF", owner, "high", "ARP spoofing (MITM preparation)",
                                     {"claimed_ip": claimed, "legit_owner": owner, "announced_mac": m.payload.get("mac"),
                                      "legit_mac": self.inventory[owner].get("mac")}, 1.0, 0.9, REC_QUARANTINE,
                                     hold_s=30.0))
            return out
        if inv is not None and (m.src, m.dst, m.protocol) not in self.allowed:
            out.append(Condition(self.LAYER, "NET-UNEXPECTED-FLOW", m.src, "medium", "Unexpected communication pattern",
                                 {"src": m.src, "dst": m.dst, "protocol": m.protocol, "kind": m.kind}, 0.7, 0.6,
                                 "Verify the communication is authorised; block at firewall if not", hold_s=15.0))
        if m.protocol == "auth":
            if m.payload.get("service") == "AS-REP" and m.payload.get("result") == "success":
                user = m.payload.get("user")
                self.sessions[m.dst] = user
                role = self.user_roles.get(user, "unknown")
                if role == "contractor" and not self.policy.get("maintenance"):
                    out.append(Condition(self.LAYER, "NET-AUTH-ANOMALY", m.dst, "medium", "Suspicious login",
                                         {"user": user, "role": role, "workstation": m.dst,
                                          "detail": "contractor login outside an approved maintenance window"},
                                         0.6, 0.6, "Confirm the login with the shift supervisor", hold_s=60.0))
            return out
        if m.protocol == "opcua" and m.dst == "TWIN-01" and m.payload.get("service") == "WriteRequest":
            node = m.payload["nodesToWrite"][0]
            if not self.policy.get("maintenance"):
                out.append(Condition(self.LAYER, "NET-TWIN-CONFIG", "TWIN-01", "medium",
                                     "Digital-twin configuration change",
                                     {"src": m.src, "user": self.sessions.get(m.src), "node": node["nodeId"],
                                      "value": node["value"], "detail": "model parameter write outside maintenance"},
                                     0.7, 0.7, "Verify change request; resynchronise / restore twin parameters",
                                     hold_s=60.0))
            return out
        if m.protocol == "modbus_tcp" and m.raw is not None:
            out.extend(self._modbus(m))
        return out

    def _modbus(self, m: Mirror) -> list[Condition]:
        out: list[Condition] = []
        is_resp = m.src in self.maps  # PLC -> client
        try:
            adu = mb.decode_adu(m.raw, is_response=is_resp)
        except mb.ModbusDecodeError as exc:
            return [Condition(self.LAYER, "NET-MALFORMED", m.src, "medium", "Invalid message sequence",
                              {"detail": f"malformed Modbus frame: {exc}", "src": m.src, "dst": m.dst}, 0.6, 0.6,
                              "Inspect source", hold_s=15.0)]
        if is_resp:
            key = (m.dst, m.src, adu.tid)
            t_req = self.pending.pop(key, None)
            if t_req is None:
                out.append(Condition(self.LAYER, "NET-UNSOLICITED", m.src, "low", "Invalid message sequence",
                                     {"detail": "Modbus response without matching request", "tid": adu.tid,
                                      "client": m.dst}, 0.4, 0.5, "Inspect for spoofed traffic", hold_s=10.0))
            else:
                self.rtt[m.src].append(m.t - t_req)
                self.answered[m.src].append(m.t)
            if adu.is_exception:
                self.exceptions[m.src].append(m.t)
            return out
        plc = m.dst
        pair = (m.src, plc)
        last = self.last_tid.get(pair)
        if last is not None:
            back = (last - adu.tid) & 0xFFFF
            if 2 < back < 30000:
                out.append(Condition(self.LAYER, "NET-TID-SEQUENCE", plc, "medium", "Invalid message sequence",
                                     {"detail": "Modbus transaction id went backwards", "src": m.src,
                                      "last_tid": last, "tid": adu.tid}, 0.6, 0.6,
                                     "Possible replay or injected session traffic", hold_s=15.0))
        if last is None or 0 < ((adu.tid - last) & 0xFFFF) < 30000:
            self.last_tid[pair] = adu.tid
        self.pending[(m.src, plc, adu.tid)] = m.t
        if adu.fc in mb.WRITE_FCS:
            self.stats["modbus_writes"] += 1
            regs = self._decode_write(plc, adu)
            reg_names = [r for r, _ in regs]
            evidence = {"src": m.src, "dst": plc, "fc": adu.fc, "tid": adu.tid,
                        "writes": [{"register": r, "value": round(v, 4)} for r, v in regs],
                        "session_user": self.sessions.get(m.src)}
            seen = self.seen_writes.get(m.raw)
            if seen is not None and m.t - seen < 900:
                out.append(Condition(self.LAYER, "NET-REPLAY", plc, "high", "Replayed command",
                                     {**evidence, "first_seen": round(seen, 2),
                                      "detail": "byte-identical write ADU (same transaction id) seen before"},
                                     1.0, 0.9, "Reject replayed commands; restore approved setpoint; quarantine source",
                                     hold_s=20.0))
            self.seen_writes[m.raw] = m.t if seen is None else seen
            if len(self.seen_writes) > 5000:
                for k in list(self.seen_writes)[:2500]:
                    del self.seen_writes[k]
            if m.src not in self.writers.get(plc, set()):
                out.append(Condition(self.LAYER, "NET-UNAUTH-WRITE", plc, "high", "Unauthorized write",
                                     {**evidence, "detail": f"{m.src} is not an authorised writer for {plc}"},
                                     1.0, 0.9, REC_REJECT, hold_s=20.0))
            else:
                cats = self.maps.get(plc, {}).get("category", {})
                user = self.sessions.get(m.src) if m.src != "SCADA-01" else None
                role = self.user_roles.get(user or "", "unknown") if user else None
                for r in reg_names:
                    cat = cats.get(r)
                    if m.src == "EWS-01" and cat == "operational" and (role not in ("engineer",) or
                                                                       not self.policy.get("maintenance")):
                        out.append(Condition(self.LAYER, "NET-POLICY-WRITE", plc, "high",
                                             "Policy violation / insider misuse",
                                             {**evidence, "role": role,
                                              "detail": f"EWS write to operational register {r} by role {role} "
                                                        f"(maintenance window: {bool(self.policy.get('maintenance'))})"},
                                             0.9, 0.8, REC_USER, hold_s=30.0))
                        break
            for r, v in regs:
                env = self.envelope.get(r)
                if env and not (env[0] <= v <= env[1]):
                    out.append(Condition(self.LAYER, "NET-WRITE-VALUE", plc, "medium", "Out-of-envelope setpoint write",
                                         {**evidence, "register": r, "value": round(v, 3), "envelope": env},
                                         0.8, 0.7, "Restore approved setpoint", hold_s=20.0))
        return out

    def _decode_write(self, plc: str, adu: mb.ModbusADU) -> list[tuple[str, float]]:
        m = self.maps.get(plc)
        if not m or adu.addr is None:
            return []
        names = m["holding"]
        vals = mb.bytes_to_floats(adu.data) if adu.fc == 16 else []
        start = adu.addr // 2
        return [(names[start + i], v) for i, v in enumerate(vals) if 0 <= start + i < len(names)]

    # ------------------------------------------------------------------ periodic rules
    def _periodic(self, t: float, window: float) -> list[Condition]:
        out: list[Condition] = []
        window = max(window, 1e-3)
        rates = {k: v / window for k, v in self.bucket.items()}
        learning = (t - (self.t0 or t)) < self.learning_s
        for k, r in rates.items():
            if learning:
                self._learn[k].append(r)
                continue
            if k not in self.baseline and k in self._learn:
                xs = self._learn[k]
                self.baseline[k] = sum(xs) / len(xs)
            base = self.baseline.get(k, 0.0)
            limit = max(3.0 * base, base + 15.0)
            if r > limit:
                since = self.rate_high_since.setdefault(k, t)
                if t - since >= 1.0 or r > 5 * limit:
                    out.append(Condition(self.LAYER, "NET-RATE", k[1], "medium", "Abnormal message rate",
                                         {"src": k[0], "dst": k[1], "rate_msgs_s": round(r, 1),
                                          "baseline_msgs_s": round(base, 1), "limit": round(limit, 1)},
                                         min(1.0, r / (limit * 3)), 0.7, REC_DOS, hold_s=8.0))
            else:
                self.rate_high_since.pop(k, None)
        for dst, n in self.dst_bucket.items():
            r = n / window
            srcs = {s for (s, d) in self.bucket if d == dst}
            if r > 150 and not learning:
                top = max(((s, self.bucket[(s, dst)]) for s in srcs), key=lambda x: x[1])
                out.append(Condition(self.LAYER, "NET-FLOOD", dst, "high", "Connection flood / DoS",
                                     {"dst": dst, "rate_msgs_s": round(r, 1), "top_source": top[0],
                                      "top_rate": round(top[1] / window, 1)}, min(1.0, r / 600), 0.85, REC_DOS,
                                     hold_s=8.0))
        self.rates = rates
        self.bucket = defaultdict(int)
        self.dst_bucket = defaultdict(int)
        for key, ts in list(self.pending.items()):
            if t - ts > 1.5:
                del self.pending[key]
                self.unanswered[key[1]].append(t)
        if not learning:
            for plc in self.maps:
                rtts = list(self.rtt[plc])[-20:]
                un = [x for x in self.unanswered[plc] if t - x <= 5.0]
                ans = [x for x in self.answered[plc] if t - x <= 5.0]
                tot = len(un) + len(ans)
                avg = sum(rtts) / len(rtts) if rtts else 0.0
                loss = len(un) / tot if tot else 0.0
                if (avg > 0.15 and rtts) or (tot >= 5 and loss > 0.2) or (tot == 0 and plc in ("PLC-1", "PLC-2")):
                    out.append(Condition(self.LAYER, "NET-COMM-DEGRADED", plc, "medium",
                                         "Communication degradation (possible DoS)",
                                         {"plc": plc, "rtt_avg_ms": round(1000 * avg, 1), "unanswered_5s": len(un),
                                          "answered_5s": len(ans), "loss_frac": round(loss, 3)},
                                         min(1.0, max(avg / 0.6, loss * 2)), 0.7, REC_DOS, hold_s=6.0))
                exc = [x for x in self.exceptions[plc] if t - x <= 5.0]
                if len(exc) >= 3:
                    out.append(Condition(self.LAYER, "NET-EXCEPTIONS", plc, "low", "Invalid message sequence",
                                         {"plc": plc, "exceptions_5s": len(exc),
                                          "detail": "repeated Modbus exception responses"}, 0.5, 0.5,
                                         "Inspect rejected requests", hold_s=10.0))
        return out

    def to_dict(self) -> dict:
        return {
            "stats": dict(self.stats),
            "sessions": dict(self.sessions),
            "top_flows": sorted(({"src": k[0], "dst": k[1], "rate": round(v, 1),
                                  "baseline": round(self.baseline.get(k, 0.0), 1)} for k, v in self.rates.items()),
                                key=lambda x: -x["rate"])[:15],
            "learning": not self.baseline,
        }
