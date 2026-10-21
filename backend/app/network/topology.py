"""Industrial network graph: nodes, links, routes and a fixed layout for the HMI.

Purdue-style zoning:
  L2 supervisory LAN (SW-SUP): SCADA, HMI, EWS, historian, twin, IDS, MQTT broker, auth
  industrial firewall FW-01
  L1 control LAN (SW-CTL): PLC-1..4, cellular gateway GW-WAN -> RTU-5 (remote tank farm)
  L0 field buses: sensors / actuators wired to their PLC
The IDS receives a SPAN copy of traffic crossing SW-SUP and SW-CTL.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Node:
    id: str
    kind: str  # server | workstation | plc | rtu | switch | firewall | gateway | ids | broker | sensor | actuator | attacker | external
    label: str
    ip: str = ""
    mac: str = ""
    zone: str = ""
    x: float = 0.0
    y: float = 0.0
    hidden: bool = False  # attacker / external nodes appear only when present
    known: bool = True  # present in the asset inventory

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "ip": self.ip, "mac": self.mac,
                "zone": self.zone, "x": self.x, "y": self.y, "hidden": self.hidden, "known": self.known}


@dataclass
class Link:
    a: str
    b: str
    medium: str  # ethernet | fieldbus | cellular | span
    latency_ms: float
    jitter_ms: float
    loss: float
    # dynamic degradation (DoS lab) — added on top of the base characteristics
    extra_delay_ms: float = 0.0
    extra_jitter_ms: float = 0.0
    extra_loss: float = 0.0
    up: bool = True
    stats: dict = field(default_factory=lambda: {"msgs": 0, "bytes": 0, "drops": 0, "lat_sum": 0.0})
    rate: dict = field(default_factory=lambda: {"msgs_s": 0.0, "bytes_s": 0.0, "drops_s": 0.0, "lat_ms": 0.0})
    suspicious: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return (self.a, self.b) if self.a < self.b else (self.b, self.a)

    @property
    def id(self) -> str:
        return f"{self.a}~{self.b}"

    def to_dict(self) -> dict:
        return {"id": self.id, "a": self.a, "b": self.b, "medium": self.medium, "latency_ms": self.latency_ms,
                "jitter_ms": self.jitter_ms, "loss": self.loss, "extra_delay_ms": self.extra_delay_ms,
                "extra_loss": self.extra_loss, "up": self.up, "rate": self.rate, "suspicious": self.suspicious}


SPAN_SWITCHES = ("SW-SUP", "SW-CTL")


class Topology:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.links: dict[tuple[str, str], Link] = {}
        self.adj: dict[str, list[str]] = {}
        self._routes: dict[tuple[str, str], Optional[list[str]]] = {}

    def add_node(self, node: Node) -> Node:
        self.nodes[node.id] = node
        self.adj.setdefault(node.id, [])
        self._routes.clear()
        return node

    def add_link(self, a: str, b: str, medium: str = "ethernet", latency_ms: float = 0.3, jitter_ms: float = 0.1,
                 loss: float = 0.0) -> Link:
        link = Link(a, b, medium, latency_ms, jitter_ms, loss)
        self.links[link.key] = link
        self.adj.setdefault(a, []).append(b)
        self.adj.setdefault(b, []).append(a)
        self._routes.clear()
        return link

    def link(self, a: str, b: str) -> Link:
        return self.links[(a, b) if a < b else (b, a)]

    def route(self, src: str, dst: str) -> Optional[list[str]]:
        key = (src, dst)
        if key in self._routes:
            return self._routes[key]
        path = self._bfs(src, dst)
        self._routes[key] = path
        return path

    def _bfs(self, src: str, dst: str) -> Optional[list[str]]:
        if src not in self.adj or dst not in self.adj:
            return None
        prev: dict[str, Optional[str]] = {src: None}
        q = deque([src])
        while q:
            u = q.popleft()
            if u == dst:
                break
            for v in self.adj[u]:
                if v not in prev:
                    lk = self.link(u, v)
                    if not lk.up:
                        continue
                    # field devices are leaves: never route *through* them
                    if v != dst and self.nodes[v].kind in ("sensor", "actuator"):
                        continue
                    prev[v] = u
                    q.append(v)
        if dst not in prev:
            return None
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])  # type: ignore[arg-type]
        return list(reversed(path))

    def to_dict(self) -> dict:
        return {"nodes": [n.to_dict() for n in self.nodes.values()],
                "links": [lk.to_dict() for lk in self.links.values()]}


INFRA = [
    # id, kind, label, ip, zone, x, y
    ("HMI-01", "workstation", "Operator HMI", "10.10.1.11", "L2", 0, 0),
    ("EWS-01", "workstation", "Engineering WS", "10.10.1.12", "L2", 170, 0),
    ("SCADA-01", "server", "SCADA Server", "10.10.1.10", "L2", 340, 0),
    ("HIST-01", "server", "Historian", "10.10.1.20", "L2", 510, 0),
    ("TWIN-01", "server", "Digital Twin", "10.10.1.30", "L2", 680, 0),
    ("IDS-01", "ids", "IDS Sensor", "10.10.1.40", "L2", 850, 0),
    ("MQTT-01", "broker", "MQTT Broker", "10.10.1.50", "L2", 1020, 0),
    ("AUTH-01", "server", "Auth / Directory", "10.10.1.60", "L2", 1190, 0),
    ("SW-SUP", "switch", "Supervisory Switch", "", "L2", 595, 130),
    ("FW-01", "firewall", "Industrial Firewall", "10.10.1.1", "DMZ", 595, 240),
    ("SW-CTL", "switch", "Control Switch", "", "L1", 595, 350),
    ("GW-WAN", "gateway", "Cellular Gateway", "10.10.2.1", "L1", 1150, 350),
    ("PLC-1", "plc", "PLC-1 Primary Loop", "10.10.2.101", "L1", 60, 480),
    ("PLC-2", "plc", "PLC-2 Secondary/Gen", "10.10.2.102", "L1", 340, 480),
    ("PLC-3", "plc", "PLC-3 Water Treatment", "10.10.2.103", "L1", 620, 480),
    ("PLC-4", "plc", "PLC-4 Chemical Mixing", "10.10.2.104", "L1", 900, 480),
    ("RTU-5", "rtu", "RTU-5 Tank Farm", "192.168.50.5", "Remote", 1180, 480),
    ("ATK-01", "attacker", "Rogue device", "10.10.2.66", "L1", 380, 350),
    ("EXT-MB", "external", "Loopback Modbus client", "127.0.0.1", "L2", 1190, 130),
]


def _mac(i: int) -> str:
    return "02:5c:ad:%02x:%02x:%02x" % ((i >> 16) & 0xFF, (i >> 8) & 0xFF, i & 0xFF)


def build_topology(field_devices: dict[str, list[tuple[str, str]]]) -> Topology:
    """field_devices: controller id -> [(device id, 'sensor'|'actuator'), ...]"""
    topo = Topology()
    for i, (nid, kind, label, ip, zone, x, y) in enumerate(INFRA):
        hidden = kind in ("attacker", "external")
        topo.add_node(Node(nid, kind, label, ip, _mac(i + 1), zone, x, y, hidden=hidden,
                           known=kind not in ("attacker", "external")))
    for nid in ("HMI-01", "EWS-01", "SCADA-01", "HIST-01", "TWIN-01", "IDS-01", "MQTT-01", "AUTH-01", "EXT-MB"):
        topo.add_link(nid, "SW-SUP", latency_ms=0.3, jitter_ms=0.1, loss=0.0)
    topo.add_link("SW-SUP", "FW-01", latency_ms=0.4, jitter_ms=0.1)
    topo.add_link("FW-01", "SW-CTL", latency_ms=0.4, jitter_ms=0.1)
    for nid in ("PLC-1", "PLC-2", "PLC-3", "PLC-4", "GW-WAN", "ATK-01"):
        topo.add_link(nid, "SW-CTL", latency_ms=0.5, jitter_ms=0.2, loss=0.0001)
    topo.add_link("GW-WAN", "RTU-5", medium="cellular", latency_ms=38.0, jitter_ms=12.0, loss=0.004)
    k = 100
    for ctrl, devs in field_devices.items():
        cx, cy = topo.nodes[ctrl].x, topo.nodes[ctrl].y
        for j, (dev_id, kind) in enumerate(devs):
            col, row = j % 3, j // 3
            k += 1
            topo.add_node(Node(dev_id, kind, dev_id, "", _mac(k), "L0", cx - 70 + col * 72, cy + 120 + row * 52))
            topo.add_link(dev_id, ctrl, medium="fieldbus", latency_ms=1.0, jitter_ms=0.3, loss=0.0002)
    return topo
