"""Protocol encoders / decoders.

Honesty about what is real and what is emulated:

* **Modbus TCP** – ``encode_*`` / ``decode_adu`` produce and parse *spec-conformant*
  Modbus Application Protocol ADUs (MBAP header + PDU, big-endian, function codes
  03/04/06/16 and exception responses).  Inside the simulation these bytes travel
  over the simulated network; the optional loopback server in
  ``modbus_server.py`` serves exactly the same bytes over a real TCP socket.
* **OPC UA** and **MQTT** – *application-level emulators*.  Messages are Python
  dicts that mirror the service / packet structure (WriteRequest,
  PublishResponse, PUBLISH with topic/QoS/packet id …) but are **not** UA Binary
  or MQTT wire frames.
* **FIELD** – emulated field-level I/O frames (stand-in for 4-20 mA/HART/IO-Link).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

PROTOCOL_INFO = {
    "modbus_tcp": {"label": "Modbus TCP", "fidelity": "spec-conformant ADU bytes (MBAP+PDU); simulated transport"},
    "opcua": {"label": "OPC UA", "fidelity": "application-level emulation (service structure only, not UA Binary)"},
    "mqtt": {"label": "MQTT", "fidelity": "application-level emulation (packet fields only, not MQTT wire frames)"},
    "field": {"label": "Field I/O", "fidelity": "emulated field-level telemetry / command frames"},
    "auth": {"label": "Auth", "fidelity": "emulated login exchange (Kerberos-like AS-REQ/AS-REP)"},
    "arp": {"label": "ARP", "fidelity": "emulated ARP announcements"},
}

FC_NAMES = {
    3: "Read Holding Registers",
    4: "Read Input Registers",
    6: "Write Single Register",
    16: "Write Multiple Registers",
    43: "Read Device Identification",
}
WRITE_FCS = {5, 6, 15, 16}

EX_ILLEGAL_FUNCTION = 0x01
EX_ILLEGAL_ADDRESS = 0x02
EX_ILLEGAL_VALUE = 0x03
EX_DEVICE_FAILURE = 0x04


class ModbusDecodeError(ValueError):
    pass


def float_to_regs(v: float) -> tuple[int, int]:
    hi, lo = struct.unpack(">HH", struct.pack(">f", v))
    return hi, lo


def regs_to_float(hi: int, lo: int) -> float:
    return struct.unpack(">f", struct.pack(">HH", hi, lo))[0]


def floats_to_bytes(values: list[float]) -> bytes:
    return struct.pack(">" + "f" * len(values), *values)


def bytes_to_floats(b: bytes) -> list[float]:
    n = len(b) // 4
    return list(struct.unpack(">" + "f" * n, b[: 4 * n]))


def _adu(tid: int, unit: int, pdu: bytes) -> bytes:
    return struct.pack(">HHHB", tid & 0xFFFF, 0, len(pdu) + 1, unit & 0xFF) + pdu


def encode_read_request(tid: int, unit: int, fc: int, addr: int, count: int) -> bytes:
    return _adu(tid, unit, struct.pack(">BHH", fc, addr, count))


def encode_read_response(tid: int, unit: int, fc: int, reg_bytes: bytes) -> bytes:
    return _adu(tid, unit, struct.pack(">BB", fc, len(reg_bytes)) + reg_bytes)


def encode_write_multiple(tid: int, unit: int, addr: int, reg_bytes: bytes) -> bytes:
    count = len(reg_bytes) // 2
    return _adu(tid, unit, struct.pack(">BHHB", 16, addr, count, len(reg_bytes)) + reg_bytes)


def encode_write_multiple_response(tid: int, unit: int, addr: int, count: int) -> bytes:
    return _adu(tid, unit, struct.pack(">BHH", 16, addr, count))


def encode_write_single(tid: int, unit: int, addr: int, value: int) -> bytes:
    return _adu(tid, unit, struct.pack(">BHH", 6, addr, value & 0xFFFF))


def encode_exception(tid: int, unit: int, fc: int, code: int) -> bytes:
    return _adu(tid, unit, struct.pack(">BB", (fc | 0x80) & 0xFF, code))


@dataclass
class ModbusADU:
    tid: int
    pid: int
    length: int
    unit: int
    fc: int
    pdu: bytes
    is_exception: bool = False
    exception_code: Optional[int] = None
    addr: Optional[int] = None
    count: Optional[int] = None
    data: bytes = b""

    def describe(self, direction: str) -> str:
        name = FC_NAMES.get(self.fc, f"FC{self.fc:02d}")
        if self.is_exception:
            return f"FC{self.fc:02d} {name} exception 0x{self.exception_code:02X}"
        return f"FC{self.fc:02d} {name} ({direction})"


def decode_adu(raw: bytes, is_response: bool) -> ModbusADU:
    """Parse an ADU. Raises ModbusDecodeError on malformed frames."""
    if len(raw) < 8:
        raise ModbusDecodeError("frame shorter than MBAP header + function code")
    tid, pid, length, unit = struct.unpack(">HHHB", raw[:7])
    if pid != 0:
        raise ModbusDecodeError(f"protocol id {pid} != 0")
    if length != len(raw) - 6:
        raise ModbusDecodeError(f"MBAP length {length} does not match frame ({len(raw) - 6})")
    pdu = raw[7:]
    fc = pdu[0]
    adu = ModbusADU(tid=tid, pid=pid, length=length, unit=unit, fc=fc & 0x7F, pdu=pdu)
    if fc & 0x80:
        adu.is_exception = True
        adu.exception_code = pdu[1] if len(pdu) > 1 else None
        return adu
    try:
        if not is_response:
            if fc in (3, 4, 6):
                adu.addr, adu.count = struct.unpack(">HH", pdu[1:5])
                if fc == 6:
                    adu.data = pdu[3:5]
                    adu.count = 1
            elif fc == 16:
                adu.addr, adu.count, nbytes = struct.unpack(">HHB", pdu[1:6])
                adu.data = pdu[6:6 + nbytes]
                if nbytes != 2 * adu.count or len(adu.data) != nbytes:
                    raise ModbusDecodeError("FC16 byte count mismatch")
        else:
            if fc in (3, 4):
                nbytes = pdu[1]
                adu.data = pdu[2:2 + nbytes]
                if len(adu.data) != nbytes:
                    raise ModbusDecodeError("read response byte count mismatch")
                adu.count = nbytes // 2
            elif fc in (6, 16):
                adu.addr, adu.count = struct.unpack(">HH", pdu[1:5])
    except struct.error as exc:  # truncated PDU
        raise ModbusDecodeError(str(exc)) from exc
    return adu


def opcua_write_request(handle: int, node_id: str, value, security: str = "None") -> dict:
    return {
        "service": "WriteRequest",
        "requestHandle": handle,
        "securityMode": security,
        "nodesToWrite": [{"nodeId": node_id, "attributeId": "Value", "value": value}],
    }


def opcua_write_response(handle: int, status: str) -> dict:
    return {"service": "WriteResponse", "requestHandle": handle, "results": [status]}


def opcua_publish_response(sub_id: int, seq: int, items: list[tuple[str, float, float]]) -> dict:
    return {
        "service": "PublishResponse",
        "subscriptionId": sub_id,
        "sequenceNumber": seq,
        "notificationMessage": {
            "dataChangeNotification": [
                {"nodeId": nid, "value": round(v, 4), "sourceTimestamp": round(ts, 3)} for nid, v, ts in items
            ]
        },
    }


def mqtt_publish(topic: str, packet_id: int, payload: dict, qos: int = 1) -> dict:
    return {"packetType": "PUBLISH", "topic": topic, "qos": qos, "packetId": packet_id, "retain": False,
            "payload": payload}
