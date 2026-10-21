import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os
    os.environ["SCADA_DB"] = str(tmp_path_factory.mktemp("db") / "t.db")
    import importlib
    import app.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_plant_and_devices(client):
    assert client.get("/api/plant/state").status_code == 200
    devs = client.get("/api/devices").json()
    assert len(devs["devices"]) > 40 and len(devs["controllers"]) == 5
    assert client.get("/api/devices/PLC-1").json()["record_type"] == "controller"
    assert client.get("/api/devices/TT-101").json()["record_type"] == "field_device"
    assert client.get("/api/devices/NOPE").status_code == 404


def test_topology_and_twin(client):
    topo = client.get("/api/network/topology").json()
    assert len(topo["nodes"]) > 60 and len(topo["links"]) > 50
    assert "health" in client.get("/api/twin/state").json()


def test_setpoint_validation(client):
    ok = client.post("/api/control/setpoint", json={"plc": "PLC-1", "register": "TIC-101.SP",
                                                     "value": 455.0, "user": "operator1"})
    assert ok.status_code == 200 and ok.json()["record"]["accepted"]
    # out of operating envelope -> 400
    bad = client.post("/api/control/setpoint", json={"plc": "PLC-1", "register": "TIC-101.SP",
                                                     "value": 9999.0, "user": "operator1"})
    assert bad.status_code == 400
    # contractor may not write -> 400
    denied = client.post("/api/control/setpoint", json={"plc": "PLC-1", "register": "TIC-101.SP",
                                                         "value": 455.0, "user": "contractor1"})
    assert denied.status_code == 400
    # schema validation: speed out of range -> 422
    assert client.post("/api/simulation/speed", json={"speed": 999}).status_code == 422


def test_attack_lifecycle(client):
    assert client.post("/api/simulation/start").status_code == 200
    r = client.post("/api/attacks/start", json={"scenario": "unauthorized_setpoint", "params": {}})
    assert r.status_code == 200 and r.json()["ok"]
    assert client.post("/api/attacks/start", json={"scenario": "nonexistent"}).status_code == 404
    assert client.post("/api/attacks/stop", json={"scenario": "unauthorized_setpoint"}).json()["ok"]


def test_watermark_endpoints(client):
    assert client.post("/api/watermarking/enable").json()["enabled"]
    assert client.post("/api/watermarking/config", json={"amplitude": 2.0}).status_code == 200
    assert client.post("/api/watermarking/config", json={"amplitude": 99}).status_code == 422
    assert not client.post("/api/watermarking/disable").json()["enabled"]


def test_response_mode(client):
    assert client.post("/api/response/mode", json={"mode": "auto"}).json()["mode"] == "auto"
    assert client.post("/api/response/mode", json={"mode": "bogus"}).status_code == 422


def test_experiment_run_and_persist(client):
    r = client.post("/api/experiments/run", json={"scenario": None, "duration": 120, "attack_at": 40,
                                                   "attack_stop": 100})
    assert r.status_code == 200
    body = r.json()
    assert "overall" in body and "by_detector_config" in body
    lst = client.get("/api/experiments").json()["experiments"]
    assert any(e["run_id"] == body["run_id"] for e in lst)


def test_websocket_snapshot(client):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        msg = ws.receive_json()
        assert msg["type"] in ("snapshot", "experiment_progress", "experiment_done")


def test_export_csv(client):
    r = client.get("/api/export/alerts")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert client.get("/api/export/bogus").status_code == 404


def test_database_persistence(tmp_path):
    from app.storage.database import Database
    db = Database(tmp_path / "x.db")
    db.log_event("run1", 1.0, "w", "alert", "twin", "high", "msg", {"a": 1})
    db.save_experiment("exp1", "lbl", "w", {"c": 1}, {"m": 2})
    assert len(db.events("run1")) == 1
    assert db.experiment("exp1")["metrics"] == {"m": 2}
    db.close()
