"""Design-invariant tests: the attacker cannot touch the twin/SIS/IDS, the twin
is independent of ground truth, and ground-truth labels never reach detectors.
"""
import dataclasses


def test_attack_context_has_no_defensive_references(engine):
    names = {f.name for f in dataclasses.fields(engine.lab.ctx)}
    for forbidden in ("twin", "ids", "safety", "sis", "watermark", "response"):
        assert forbidden not in names, f"attacker must not have access to {forbidden}"


def test_twin_does_not_read_ground_truth():
    """The DigitalTwin's physics state must diverge from the plant's hidden state
    when telemetry is falsified: it cannot be silently copying the real value."""
    from app.simulation.engine import EngineConfig, SimulationEngine
    e = SimulationEngine(EngineConfig(seed=5))
    e.step_many(400)
    # falsify TT-101 downward; real T_hl keeps rising, twin should track reality, not the lie
    e.lab.start("false_data_injection", {"tag": "TT-101", "mode": "bias", "bias": -20.0}, e.t)
    e.step_many(200)
    real = e.plant.physical["boiler.T_hl"]
    observed = e.scada.value("TT-101")
    twin_pred = e.twin.pred["TT-101"]
    assert abs(observed - real) > 10.0          # telemetry really is falsified
    assert abs(twin_pred - real) < abs(twin_pred - observed)  # twin tracks reality, not the lie


def test_false_data_keeps_physical_process_evolving():
    """A falsified low reading makes the controller over-drive the heater, so the real
    temperature diverges from the (frozen/biased) telemetry — the physical process is
    not affected by *what the attacker shows the operator*, only by real actuator action."""
    from app.simulation.engine import EngineConfig, SimulationEngine
    e = SimulationEngine(EngineConfig(seed=5))
    e.step_many(300)
    before = e.plant.physical["boiler.T_hl"]
    e.lab.start("false_data_injection", {"tag": "TT-101", "mode": "bias", "bias": -20.0}, e.t)
    e.step_many(250)
    observed = e.scada.value("TT-101")
    real = e.plant.physical["boiler.T_hl"]
    # the real temperature moved substantially while the operator sees a ~biased value
    assert abs(real - before) > 2.0
    assert abs(real - observed) > 10.0


def test_ids_mirror_has_no_ground_truth_field():
    from app.network.traffic import Mirror
    fields = {f.name for f in dataclasses.fields(Mirror)}
    assert "gt_attack" not in fields and "spoofed_src" not in fields


def test_starting_scenario_alone_raises_no_alert():
    """Detection must come from observed evidence, not the act of starting a scenario."""
    from app.simulation.engine import EngineConfig, SimulationEngine
    e = SimulationEngine(EngineConfig(seed=9))
    e.step_many(300)
    n_before = len(e.ids.findings.all)
    # a scenario whose effect is delayed (replay captures first) raises nothing immediately
    e.lab.start("command_replay", {}, e.t)
    e.step_many(3)  # 0.3 s — not enough to capture+replay
    assert len(e.ids.findings.all) == n_before
