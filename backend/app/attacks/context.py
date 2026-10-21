"""Capabilities granted to the simulated attacker.

The attack laboratory can only:
* intercept / inject / sniff messages on the simulated network,
* tamper with field-device firmware hooks (sensor output, actuator response),
* drive a compromised engineering workstation (or an insider's session),
* apply a physical degradation (heat-exchanger fouling) through a narrow API.

It is **never** given the safety system, the IDS, the digital twin or the
watermark engine.  ``tests/test_isolation.py`` checks this.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.network.topology import Topology
from app.network.traffic import NetworkBus
from app.simulation.devices import Actuator, Sensor
from app.simulation.scada import Workstation


class PhysicalAccess:
    def __init__(self, set_fouling: Callable[[float], None], get_fouling: Callable[[], float]):
        self._set, self._get = set_fouling, get_fouling

    def set_hx_fouling(self, factor: float) -> None:
        self._set(max(0.2, min(1.0, factor)))

    def hx_fouling(self) -> float:
        return self._get()


@dataclass
class AttackContext:
    bus: NetworkBus
    topology: Topology
    sensors: dict[str, Sensor]
    actuators: dict[str, Actuator]
    ews: Workstation
    register_maps: dict[str, dict]  # attacker reconnaissance: PLC register layout
    physical: PhysicalAccess
    lab_restore_setpoints: Callable[[float], None]  # lab clean-up: SCADA re-writes approved values
    lab_login: Callable[[str, str, float], None]  # (workstation, user, t) -> sends a login on the network
    lab_logout: Callable[[str, float], None]
