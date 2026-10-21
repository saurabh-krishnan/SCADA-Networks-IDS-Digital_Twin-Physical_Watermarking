import pytest

from app.simulation.engine import EngineConfig, SimulationEngine


@pytest.fixture
def engine():
    return SimulationEngine(EngineConfig(seed=1337))


@pytest.fixture
def settled_engine():
    e = SimulationEngine(EngineConfig(seed=1337))
    e.step_many(300)  # 30 s past warm-up
    return e
