import numpy as np

from app.digital_twin.residuals import ResidualConfig, ResidualTracker
from app.watermarking.signal import WatermarkSignal


def test_watermark_signal_reproducible_and_bounded():
    a = WatermarkSignal(seed=42, amplitude=1.5, hold_s=1.0, mode="prbs")
    b = WatermarkSignal(seed=42, amplitude=1.5, hold_s=1.0, mode="prbs")
    seq_a = a.sequence(100)
    seq_b = b.sequence(100)
    assert seq_a == seq_b                       # reproducible from seed
    assert all(abs(x) <= 1.5 + 1e-9 for x in seq_a)  # bounded by amplitude
    assert set(round(abs(x), 6) for x in seq_a) == {1.5}  # prbs is +/-amplitude
    # different seed -> different sequence
    c = WatermarkSignal(seed=43, amplitude=1.5, hold_s=1.0, mode="prbs")
    assert c.sequence(100) != seq_a


def test_watermark_hold_time():
    s = WatermarkSignal(seed=1, amplitude=1.0, hold_s=2.0, mode="prbs")
    assert s.value(0.0, 0.0) == s.value(1.9, 0.0)      # same slot
    # value is zero before activation
    assert s.value(-1.0, 0.0) == 0.0


def test_residual_tracker_quiet_under_noise():
    cfg = ResidualConfig(calib_s=5.0)
    tr = ResidualTracker("T", sigma=1.0, cfg=cfg)
    rng = np.random.default_rng(0)
    t = 0.0
    for _ in range(600):
        tr.update(t, 100.0 + rng.normal(0, 1.0), 100.0, True)
        t += 0.1
    assert not tr.persistent and not tr.sudden
    assert tr.score < 0.5


def test_residual_tracker_detects_persistent_bias():
    cfg = ResidualConfig(calib_s=5.0)
    tr = ResidualTracker("T", sigma=1.0, cfg=cfg)
    rng = np.random.default_rng(0)
    t = 0.0
    for _ in range(100):  # calibrate clean
        tr.update(t, 100.0 + rng.normal(0, 1.0), 100.0, True)
        t += 0.1
    assert not tr.calibrating
    for _ in range(200):  # inject a persistent +5 sigma bias
        tr.update(t, 105.0 + rng.normal(0, 1.0), 100.0, True)
        t += 0.1
    assert tr.persistent
    assert tr.score >= 1.0


def test_watermark_engine_baseline_consistent():
    """End-to-end: under clean operation the watermark decision becomes 'consistent'."""
    from app.simulation.engine import EngineConfig, SimulationEngine
    e = SimulationEngine(EngineConfig(seed=7))
    e.watermark.enable(e.t)
    e.step_many(700)
    assert e.watermark.injecting
    assert e.watermark.decision == "consistent"
    for ch in e.watermark.ch.values():
        assert ch.beta0 is not None and ch.beta0 > 0.3


def test_watermark_suspends_on_safety_trip():
    from app.simulation.engine import EngineConfig, SimulationEngine
    e = SimulationEngine(EngineConfig(seed=7))
    e.watermark.enable(e.t)
    e.step_many(100)
    e.safety.trigger_esd(e.t)
    e.step_many(30)
    assert not e.watermark.injecting
    assert e.watermark.suspended_reason is not None
