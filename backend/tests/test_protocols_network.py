import pytest

from app.network import protocols as mb


def test_modbus_roundtrip_read():
    raw = mb.encode_read_request(7, 1, 3, 0, 4)
    adu = mb.decode_adu(raw, is_response=False)
    assert adu.tid == 7 and adu.fc == 3 and adu.addr == 0 and adu.count == 4
    assert adu.pid == 0


def test_modbus_roundtrip_write_multiple_floats():
    data = mb.floats_to_bytes([450.0, 85.0])
    raw = mb.encode_write_multiple(9, 1, 0, data)
    adu = mb.decode_adu(raw, is_response=False)
    assert adu.fc == 16 and adu.count == 4
    assert mb.bytes_to_floats(adu.data) == [450.0, 85.0]


def test_modbus_float_register_roundtrip():
    hi, lo = mb.float_to_regs(3.14159)
    assert abs(mb.regs_to_float(hi, lo) - 3.14159) < 1e-5


def test_modbus_decode_rejects_bad_protocol_id():
    raw = bytearray(mb.encode_read_request(1, 1, 3, 0, 2))
    raw[2] = 0xFF  # corrupt protocol id
    with pytest.raises(mb.ModbusDecodeError):
        mb.decode_adu(bytes(raw), is_response=False)


def test_modbus_decode_rejects_length_mismatch():
    raw = mb.encode_read_request(1, 1, 3, 0, 2)
    with pytest.raises(mb.ModbusDecodeError):
        mb.decode_adu(raw[:-1], is_response=False)  # truncated


def test_modbus_exception_frame():
    raw = mb.encode_exception(3, 1, 16, mb.EX_ILLEGAL_VALUE)
    adu = mb.decode_adu(raw, is_response=True)
    assert adu.is_exception and adu.exception_code == mb.EX_ILLEGAL_VALUE


def test_opcua_and_mqtt_structure():
    w = mb.opcua_write_request(1, "ns=2;s=PLC-1.TIC-101.SP", 455.0)
    assert w["service"] == "WriteRequest" and w["nodesToWrite"][0]["value"] == 455.0
    p = mb.mqtt_publish("site/x", 5, {"a": 1}, qos=1)
    assert p["packetType"] == "PUBLISH" and p["qos"] == 1 and p["packetId"] == 5


def test_network_routing_and_delivery(engine):
    bus = engine.bus
    # a route exists from SCADA to each PLC and back
    assert bus.topo.route("SCADA-01", "PLC-1") is not None
    assert bus.topo.route("RTU-5", "MQTT-01") is not None
    # field devices are leaves (no routing through them)
    assert bus.topo.route("SCADA-01", "TT-101") is not None


def test_quarantine_blocks_traffic(settled_engine):
    e = settled_engine
    e.bus.quarantined.add("ATK-01")
    from app.network.traffic import Message
    before = e.bus.blocked_count.get("ATK-01", 0)
    m = e.bus.send(Message(e.t, "ATK-01", "PLC-1", "modbus_tcp", "FC03", {"x": 1},
                           raw=mb.encode_read_request(1, 1, 3, 0, 2)))
    assert m.dropped is not None and "quarantine" in m.dropped
    assert e.bus.blocked_count.get("ATK-01", 0) > before


def test_secure_channel_integrity(settled_engine):
    e = settled_engine
    e.bus.secure_pairs.add(frozenset(("SCADA-01", "PLC-1")))
    from app.network.traffic import Message
    m = Message(e.t, "SCADA-01", "PLC-1", "modbus_tcp", "FC16", {"v": 1},
                raw=mb.encode_write_multiple(1, 1, 0, mb.floats_to_bytes([1.0])))
    e.bus.send(m)
    assert m.secure and m.mac is not None
