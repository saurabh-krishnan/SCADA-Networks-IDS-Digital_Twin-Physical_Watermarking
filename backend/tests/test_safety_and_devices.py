import numpy as np

from app.core.rng import NoiseStream
from app.simulation.devices import Actuator, AlarmLimits, Sensor


def _ns():
    return NoiseStream(np.random.default_rng(1))


def test_alarm_limits_classify():
    lim = AlarmLimits(lo_lo=0, lo=10, hi=90, hi_hi=100)
    assert lim.classify(50) == "normal"
    assert lim.classify(95) == "alarm"
    assert lim.classify(100) == "critical"
    assert lim.classify(5) == "alarm"
    assert lim.classify(-1) == "critical"


def test_sensor_sampling_noise_and_quantisation():
    s = Sensor(id="X", name="x", noise_sigma=0.5, resolution=0.1, range_lo=0, range_hi=100, noise=_ns())
    vals = [s.sample(0.0, 50.0) for _ in range(200)]
    assert abs(sum(vals) / len(vals) - 50.0) < 0.3           # unbiased
    assert all(abs(round(v / 0.1) * 0.1 - v) < 1e-9 for v in vals)  # quantised
    assert np.std(vals) > 0.1                                 # noisy


def test_sensor_range_clamp():
    s = Sensor(id="X", name="x", noise_sigma=0.0, range_lo=0, range_hi=10, noise=_ns())
    assert s.sample(0.0, 99.0) == 10.0
    assert s.sample(0.0, -5.0) == 0.0


def test_actuator_rate_limit_and_saturation():
    a = Actuator(id="A", name="a", lo=0, hi=100, rate_limit=10.0, tau=0.0)
    a.set_command(100.0)
    a.step(0.1)
    assert a.output <= 1.0 + 1e-6            # 10 %/s * 0.1 s
    for _ in range(200):
        a.step(0.1)
    assert abs(a.output - 100.0) < 1e-6      # saturates at command


def test_actuator_command_clamped_to_range():
    a = Actuator(id="A", name="a", lo=0, hi=100, rate_limit=1e9)
    a.set_command(500.0)
    assert a.command == 100.0
    a.set_command(-10.0)
    assert a.command == 0.0


def test_safety_trip_independent_of_firmware_hook():
    """A firmware hook forcing an actuator open must not defeat a safety trip."""
    a = Actuator(id="HTR", name="h", lo=0, hi=100, rate_limit=1e9)
    a.firmware_hook = {"stuck": 100.0}       # attacker jams heater full-on
    a.trip_override = 0.0                     # SIS forces it off
    a.set_command(100.0)
    a.step(0.1)
    assert a.output == 0.0                    # safety wins


def test_safety_system_trips_and_latches(engine):
    sis = engine.safety
    # force the physical hot-leg temperature above the TSHH-101 limit
    engine.plant.boiler.T_hl = 600.0
    engine.plant._refresh_state()
    sis.evaluate(engine.t)
    assert sis.tripped
    assert any(r == "TSHH-101" for r in sis.latched)
    assert engine.plant.actuators["HTR-101"].trip_override == 0.0
    # reset while condition persists -> stays latched
    res = sis.reset(engine.t)
    assert "TSHH-101" in res["still_active"]
    # clear condition, then reset succeeds
    engine.plant.boiler.T_hl = 450.0
    engine.plant._refresh_state()
    sis.evaluate(engine.t)
    res2 = sis.reset(engine.t)
    assert not sis.tripped


def test_emergency_shutdown_cannot_be_disabled_by_attacker(engine):
    """The attack lab has no reference to the safety system."""
    import dataclasses
    fields = {f.name for f in dataclasses.fields(engine.lab.ctx)}
    assert "safety" not in fields and "sis" not in fields
    # and ESD forces the heater off regardless of any actuator firmware hook
    engine.plant.actuators["HTR-101"].firmware_hook = {"stuck": 100.0}
    engine.safety.trigger_esd(engine.t)
    engine.plant.step(0.1)
    assert engine.plant.actuators["HTR-101"].output == 0.0
