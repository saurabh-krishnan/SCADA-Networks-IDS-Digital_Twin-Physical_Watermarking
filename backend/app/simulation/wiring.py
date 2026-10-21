"""Static wiring derived from the plant + controllers: register maps, allowed
network flows, authorised writers and the asset inventory used by the IDS.
"""
from __future__ import annotations

from app.network.topology import Topology
from app.simulation.plant import Plant
from app.simulation.plc import PLC


def build_register_maps(controllers: dict[str, PLC]) -> dict[str, dict]:
    maps: dict[str, dict] = {}
    for cid, plc in controllers.items():
        maps[cid] = {
            "unit": plc.unit_id,
            "inputs": list(plc.inp.names),
            "holding": list(plc.hold.names),
            "category": {h.name: h.category for h in plc.holding_spec.values()},
            "initial_holding": {h: plc.hold.values[h] for h in plc.hold.names},
        }
    return maps


def build_allowed_flows(controllers: dict[str, PLC]) -> set[tuple[str, str, str]]:
    """Expected (src, dst, protocol) pairs for normal operation (both directions)."""
    flows: set[tuple[str, str, str]] = set()
    for cid, plc in controllers.items():
        proto = plc.protocol
        if proto == "modbus_tcp":
            flows.add(("SCADA-01", cid, "modbus_tcp"))
            flows.add((cid, "SCADA-01", "modbus_tcp"))
            flows.add(("EWS-01", cid, "modbus_tcp"))
            flows.add((cid, "EWS-01", "modbus_tcp"))
    # MQTT (RTU-5 telemetry/commands via broker)
    flows |= {("RTU-5", "MQTT-01", "mqtt"), ("MQTT-01", "SCADA-01", "mqtt"), ("SCADA-01", "MQTT-01", "mqtt"),
              ("MQTT-01", "RTU-5", "mqtt")}
    # supervisory services
    flows |= {("SCADA-01", "HIST-01", "opcua"), ("SCADA-01", "TWIN-01", "opcua"),
              ("HMI-01", "AUTH-01", "auth"), ("AUTH-01", "HMI-01", "auth"),
              ("EWS-01", "AUTH-01", "auth"), ("AUTH-01", "EWS-01", "auth"),
              ("SCADA-01", "AUTH-01", "auth"), ("AUTH-01", "SCADA-01", "auth"),
              ("HMI-01", "SCADA-01", "opcua"), ("SCADA-01", "HMI-01", "opcua"),
              ("EWS-01", "SCADA-01", "opcua"), ("SCADA-01", "EWS-01", "opcua"),
              ("EXT-MB", "SCADA-01", "modbus_tcp"), ("SCADA-01", "EXT-MB", "modbus_tcp")}
    # field buses (sensor->plc, plc->actuator)
    for cid, plc in controllers.items():
        for sid in plc.sensor_ids:
            flows.add((sid, cid, "field"))
        for aid in plc.actuator_ids:
            flows.add((cid, aid, "field"))
            flows.add((aid, cid, "field"))
    return flows


def build_inventory(topo: Topology) -> dict[str, dict]:
    return {n.id: {"ip": n.ip, "mac": n.mac, "kind": n.kind, "zone": n.zone}
            for n in topo.nodes.values() if n.known}


def build_authorized_writers(controllers: dict[str, PLC]) -> dict[str, set[str]]:
    writers: dict[str, set[str]] = {}
    for cid, plc in controllers.items():
        if plc.protocol == "modbus_tcp":
            writers[cid] = {"SCADA-01", "EWS-01"}
        else:
            writers[cid] = {"MQTT-01"}
    return writers


def register_owner_map(controllers: dict[str, PLC]) -> dict[str, str]:
    owner: dict[str, str] = {}
    for cid, plc in controllers.items():
        for h in plc.hold.names:
            owner.setdefault(h, cid)
    return owner
