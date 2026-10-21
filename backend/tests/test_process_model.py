import math

import numpy as np
import pytest

from app.core.rng import NoiseStream
from app.simulation.boiler import BoilerLoop, BoilerParams, ntu_effectiveness, pump_flow_ss


def _ns():
    return NoiseStream(np.random.default_rng(0))


def test_ntu_effectiveness_bounds():
    for ua in (0.1, 5, 50, 500):
        eps, cmin = ntu_effectiveness(ua, 20.0, 60.0)
        assert 0.0 <= eps <= 1.0
        assert cmin == 20.0
    # higher UA -> higher effectiveness (monotone)
    e1, _ = ntu_effectiveness(5, 20, 60)
    e2, _ = ntu_effectiveness(50, 20, 60)
    assert e2 > e1


def test_pump_curve_monotonic():
    p = BoilerParams()
    f50 = pump_flow_ss(p, 0.5, 0.8)
    f100 = pump_flow_ss(p, 1.0, 0.8)
    assert f100 > f50 > 0
    # closing the valve reduces flow
    assert pump_flow_ss(p, 1.0, 0.4) < pump_flow_ss(p, 1.0, 1.0)


def test_energy_balance_steady_state():
    """At the design steady state dT/dt ~ 0 for the boiler node."""
    p = BoilerParams()
    loop = BoilerLoop(p, _ns())
    out = loop.init_steady_state(450.0, 220.0, 85.0, 80.0, 80.0, 300.0)
    # step with the holding actuator outputs; temperatures should barely move
    T0 = loop.T_b
    for _ in range(50):
        loop.step(0.1, out["heater_pct"], 85.0, 80.0, 80.0, out["fan_pct"], 300.0)
    assert abs(loop.T_b - T0) < 5.0, f"boiler drifted {loop.T_b - T0:.2f} from steady state"


def test_heater_raises_temperature():
    p = BoilerParams()
    loop = BoilerLoop(p, _ns())
    loop.init_steady_state(450.0, 220.0, 85.0, 80.0, 80.0, 300.0)
    T0 = loop.T_b
    for _ in range(300):
        loop.step(0.1, 100.0, 85.0, 80.0, 80.0, 0.0, 300.0)  # max heater, no cooling
    assert loop.T_b > T0 + 5.0


def test_flow_responds_to_pump_speed():
    p = BoilerParams()
    loop = BoilerLoop(p, _ns())
    loop.init_steady_state(450.0, 220.0, 85.0, 80.0, 80.0, 300.0)
    m0 = loop.m
    for _ in range(60):
        loop.step(0.1, 60.0, 40.0, 80.0, 80.0, 50.0, 300.0)  # slow the pump
    assert loop.m < m0


def test_no_nan_under_extremes():
    p = BoilerParams()
    loop = BoilerLoop(p, _ns())
    loop.init_steady_state(450.0, 220.0, 85.0, 80.0, 80.0, 300.0)
    for _ in range(200):
        loop.step(0.1, 100.0, 100.0, 100.0, 100.0, 0.0, 450.0)
    for v in loop.state().values():
        assert math.isfinite(v)
