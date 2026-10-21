import pytest

from app.ids.base import Condition, FindingManager
from app.ids.correlation import classify


def test_finding_manager_dedup():
    fm = FindingManager()
    c = Condition("network", "NET-UNAUTH-WRITE", "PLC-1", "high", "Unauthorized write", {}, 1.0, 0.9, "x", hold_s=5.0)
    f1 = fm.report(1.0, c)
    f2 = fm.report(1.5, c)
    assert f1 is f2 and f2.count == 2             # same finding, not duplicated
    assert len([e for e in fm.new_events if e[0] == "raised"]) == 1


def test_finding_clears_after_hold():
    fm = FindingManager()
    c = Condition("process", "PROC-LIMIT", "TT-101", "low", "limit", {}, 1.0, 0.5, "x", hold_s=2.0)
    fm.report(0.0, c)
    fm.sweep(1.0)
    assert fm.active                               # still within hold
    fm.sweep(5.0)
    assert not fm.active                           # cleared


def test_classification_rules():
    assert classify({"NET-REPLAY"}, []) == "Command replay"
    assert classify({"NET-UNAUTH-WRITE"}, []) == "Unauthorized setpoint modification"
    assert classify({"NET-FLOOD"}, []) == "Denial of service"
    assert classify({"NET-POLICY-WRITE"}, []) == "Insider misuse"


def test_clean_run_has_no_false_positives():
    from app.simulation.engine import EngineConfig, SimulationEngine
    e = SimulationEngine(EngineConfig(seed=1337))
    e.step_many(1000)  # 100 s clean
    active = [f for f in e.ids.findings.active.values() if f.severity != "info"]
    assert active == [], f"unexpected alerts on a clean run: {[(f.rule, f.asset) for f in active]}"


@pytest.mark.parametrize("scenario,expected_layer", [
    ("false_data_injection", "twin"),
    ("unauthorized_setpoint", "network"),
    ("frozen_sensor", "process"),
])
def test_scenarios_detected_by_expected_layer(scenario, expected_layer):
    from app.simulation.engine import EngineConfig, SimulationEngine
    e = SimulationEngine(EngineConfig(seed=1337))
    e.step_many(450)
    e.lab.start(scenario, {}, e.t)
    e.step_many(400)
    layers = {f.layer for f in e.ids.findings.active.values() if f.severity != "info"}
    assert expected_layer in layers, f"{scenario} not detected by {expected_layer}; got {layers}"


def test_network_only_misses_sensor_falsification():
    """Core research result: a pure sensor-telemetry lie yields no network-layer evidence."""
    from app.experiments.runner import ExperimentConfig, run_experiment
    r = run_experiment(ExperimentConfig(scenario="false_data_injection",
                                        scenario_params={"tag": "TT-101", "mode": "bias", "bias": -18.0},
                                        duration=180, attack_at=50, attack_stop=140))
    assert r["by_detector_config"]["network_only"]["detected"] is False
    assert r["by_detector_config"]["network_process"]["detected"] is True


def test_experiment_no_attack_no_detection():
    from app.experiments.runner import ExperimentConfig, run_experiment
    r = run_experiment(ExperimentConfig(scenario=None, duration=150))
    assert r["overall"]["attack_windows"] == 0
    assert r["overall"]["fp"] == 0


def test_experiment_metrics_consistent():
    from app.experiments.runner import ExperimentConfig, run_experiment
    r = run_experiment(ExperimentConfig(scenario="unauthorized_setpoint", duration=180, attack_at=50, attack_stop=140))
    m = r["by_detector_config"]["full"]
    assert 0.0 <= m["precision"] <= 1.0 and 0.0 <= m["recall"] <= 1.0 and 0.0 <= m["f1"] <= 1.0
    assert m["detected"] is True
