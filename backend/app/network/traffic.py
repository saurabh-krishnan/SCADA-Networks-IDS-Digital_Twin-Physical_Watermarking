"""Discrete-event message bus that carries all simulated industrial traffic.

Each ``send`` walks the routed path hop by hop:
  quarantine / firewall check -> loss -> man-in-the-middle interceptors -> SPAN mirror
and schedules delivery after the accumulated latency.  ``run_until`` delivers
messages (and timer callbacks) in time order, so a SCADA poll and its response
can complete inside one 100 ms simulation tick while DoS-delayed messages spill
into later ticks.

Ground truth: ``Message.gt_attack`` is set *only* by the attack laboratory and
is used by the experiment evaluator.  Detection code never receives it — the
SPAN mirror hands the IDS a ``Mirror`` record that does not contain the field.
"""
from __future__ import annotations

import hashlib
import hmac
import heapq
import itertools
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.core.rng import hash_uniform, stable_id
from app.network.topology import SPAN_SWITCHES, Topology


@dataclass(slots=True)
class Message:
    t_sent: float
    src: str
    dst: str
    protocol: str
    kind: str
    payload: dict
    raw: Optional[bytes] = None
    user: Optional[str] = None
    seq: Optional[int] = None
    id: int = 0
    size: int = 0
    t_deliver: float = 0.0
    latency_ms: float = 0.0
    secure: bool = False
    mac: Optional[bytes] = None
    dropped: Optional[str] = None
    path: tuple = ()
    ids_label: Optional[str] = None
    spoofed_src: Optional[str] = None  # physical sender when the source address is forged (routing + MAC only)
    gt_attack: Optional[str] = None  # GROUND TRUTH (lab only)

    def summary(self) -> dict:
        d = {
            "id": self.id, "t": round(self.t_sent, 3), "src": self.src, "dst": self.dst, "protocol": self.protocol,
            "kind": self.kind, "size": self.size, "latency_ms": round(self.latency_ms, 2), "seq": self.seq,
            "user": self.user, "secure": self.secure, "dropped": self.dropped, "ids_label": self.ids_label,
            "payload": _compact(self.payload),
            "gt_attack": self.gt_attack,
        }
        if self.raw is not None:
            d["hex"] = self.raw[:64].hex(" ")
        return d


def _compact(p: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "…"
    if isinstance(p, dict):
        items = list(p.items())[:14]
        return {k: _compact(v, depth + 1) for k, v in items}
    if isinstance(p, list):
        return [_compact(v, depth + 1) for v in p[:10]]
    if isinstance(p, float):
        return round(p, 4)
    return p


@dataclass(slots=True)
class Mirror:
    """What the IDS sees on the SPAN port (no ground-truth fields)."""
    t: float
    msg_id: int
    src: str
    dst: str
    protocol: str
    kind: str
    raw: Optional[bytes]
    payload: dict
    size: int
    user: Optional[str]
    secure: bool
    src_mac: str = ""


InterceptFn = Callable[[Message, float], Optional[str]]  # returns None | "drop" | "delay:<sec>"


@dataclass
class Interceptor:
    name: str
    link: tuple[str, str]  # (a, b) — order-insensitive
    fn: InterceptFn
    attack_id: str = ""


class NetworkBus:
    SECRET = b"lab-secure-channel-key"

    def __init__(self, topo: Topology, seed: int):
        self.topo = topo
        self.seed = seed
        self.t = 0.0
        self._heap: list = []
        self._ctr = itertools.count()
        self._ids = itertools.count(1)
        self.handlers: dict[str, Callable[[Message], None]] = {}
        self.interceptors: list[Interceptor] = []
        self.span_taps: list[Callable[[Mirror], None]] = []
        self.capture_taps: list[Callable[[Message], None]] = []  # attacker passive sniffing (lab)
        self.quarantined: set[str] = set()
        self.secure_pairs: set[frozenset] = set()
        self.flow_seq: dict[tuple[str, str], int] = {}
        self.recent: deque[dict] = deque(maxlen=600)
        self.recent_sample_every = 1
        self._recent_counter = 0
        self.integrity_failures: list[dict] = []
        self.node_stats: dict[str, dict] = {}
        self.blocked_count: dict[str, int] = {}
        self.events: list[dict] = []  # bus-level security events (integrity failures, quarantine drops)
        self.mac_override: dict[str, str] = {}  # ARP poisoning (lab): ip owner -> attacker MAC on the wire
        self.record = True  # keep a UI sample of recent messages (disabled for headless experiments)

    # ------------------------------------------------------------------ API
    def register(self, node_id: str, handler: Callable[[Message], None]) -> None:
        self.handlers[node_id] = handler

    def schedule(self, t: float, fn: Callable[[], None]) -> None:
        heapq.heappush(self._heap, (t, next(self._ctr), fn))

    def secure_pair(self, a: str, b: str) -> bool:
        return frozenset((a, b)) in self.secure_pairs

    def send(self, msg: Message) -> Message:
        msg.id = next(self._ids)
        if msg.size == 0:
            msg.size = (len(msg.raw) + 54) if msg.raw is not None else 120 + 8 * len(msg.payload)
        if self.secure_pair(msg.src, msg.dst):
            msg.secure = True
            msg.mac = self._mac(msg)
        flow = (msg.src, msg.dst)
        fs = self.flow_seq.get(flow, 0) + 1
        self.flow_seq[flow] = fs
        fid = stable_id(msg.src + ">" + msg.dst)
        path = self.topo.route(msg.spoofed_src or msg.src, msg.dst)
        st = self.node_stats.setdefault(msg.src, {"out": 0, "in": 0})
        st["out"] += 1
        if not path:
            msg.dropped = "no route"
            self._record(msg)
            return msg
        msg.path = tuple(path)
        lat = 0.0
        mirrored = False
        for hop in range(len(path) - 1):
            a, b = path[hop], path[hop + 1]
            link = self.topo.link(a, b)
            phys = msg.spoofed_src or msg.src
            if (phys in self.quarantined or msg.dst in self.quarantined) and b in SPAN_SWITCHES + ("FW-01",):
                msg.dropped = f"blocked (quarantine) at {b}"
                q = phys if phys in self.quarantined else msg.dst
                self.blocked_count[q] = self.blocked_count.get(q, 0) + 1
                link.stats["drops"] += 1
                self._record(msg)
                return msg
            u = hash_uniform(self.seed, fid, fs, hop)
            u2 = hash_uniform(self.seed, fid, fs, hop, 7)
            loss = link.loss + link.extra_loss
            link.stats["msgs"] += 1
            link.stats["bytes"] += msg.size
            if u < loss:
                msg.dropped = f"lost on {a}-{b}"
                link.stats["drops"] += 1
                self._record(msg)
                return msg
            hop_lat = (link.latency_ms + link.extra_delay_ms + (link.jitter_ms + link.extra_jitter_ms) * (2 * u2 - 1)
                       if link.jitter_ms or link.extra_jitter_ms else link.latency_ms + link.extra_delay_ms)
            hop_lat = max(0.05, hop_lat)
            lat += hop_lat
            link.stats["lat_sum"] += hop_lat
            for ic in self.interceptors:
                if ic.link == (a, b) or ic.link == (b, a):
                    res = ic.fn(msg, msg.t_sent + lat / 1000.0)
                    if res == "drop":
                        msg.dropped = f"dropped in transit ({a}-{b})"
                        link.stats["drops"] += 1
                        self._record(msg)
                        return msg
                    if res and res.startswith("delay:"):
                        lat += 1000.0 * float(res.split(":", 1)[1])
            if not mirrored and b in SPAN_SWITCHES:
                mirrored = True
                src_node = self.topo.nodes.get(msg.src)
                mac = self.mac_override.get(msg.src, src_node.mac if src_node else "")
                if msg.spoofed_src:
                    att = self.topo.nodes.get(msg.spoofed_src)
                    mac = att.mac if att else mac
                mir = Mirror(msg.t_sent + lat / 1000.0, msg.id, msg.src, msg.dst, msg.protocol, msg.kind, msg.raw,
                             msg.payload, msg.size, msg.user, msg.secure, mac)
                for tap in self.span_taps:
                    tap(mir)
        for tap in self.capture_taps:
            tap(msg)
        msg.latency_ms = lat
        msg.t_deliver = msg.t_sent + lat / 1000.0
        heapq.heappush(self._heap, (msg.t_deliver, next(self._ctr), msg))
        return msg

    def run_until(self, t_end: float) -> None:
        heap = self._heap
        while heap and heap[0][0] <= t_end:
            t, _, item = heapq.heappop(heap)
            self.t = max(self.t, t)
            if callable(item):
                item()
                continue
            msg: Message = item
            if msg.secure and msg.mac is not None and not hmac.compare_digest(msg.mac, self._mac(msg)):
                msg.dropped = "integrity check failed (MAC mismatch) — discarded by receiver"
                ev = {"t": t, "src": msg.src, "dst": msg.dst, "kind": msg.kind}
                self.integrity_failures.append(ev)
                self.events.append({"type": "integrity_failure", **ev})
                self._record(msg)
                continue
            st = self.node_stats.setdefault(msg.dst, {"out": 0, "in": 0})
            st["in"] += 1
            self._record(msg)
            h = self.handlers.get(msg.dst)
            if h is not None:
                h(msg)

    def pending(self) -> int:
        return len(self._heap)

    def roll_stats(self, window_s: float) -> None:
        for link in self.topo.links.values():
            s = link.stats
            link.rate = {
                "msgs_s": round(s["msgs"] / window_s, 1),
                "bytes_s": round(s["bytes"] / window_s, 1),
                "drops_s": round(s["drops"] / window_s, 2),
                "lat_ms": round(s["lat_sum"] / s["msgs"], 2) if s["msgs"] else 0.0,
            }
            link.stats = {"msgs": 0, "bytes": 0, "drops": 0, "lat_sum": 0.0}

    # ------------------------------------------------------------------ internals
    def _mac(self, msg: Message) -> bytes:
        body = msg.raw if msg.raw is not None else repr(sorted(msg.payload.items())).encode()
        return hmac.new(self.SECRET, f"{msg.src}>{msg.dst}|".encode() + body, hashlib.sha256).digest()[:16]

    def _record(self, msg: Message) -> None:
        if not self.record:
            return
        if msg.protocol == "field":
            self._recent_counter += 1
            if msg.dropped is None and self._recent_counter % 25:
                return  # keep only a sample of high-rate field telemetry for the UI
        self.recent.append(msg.summary())
