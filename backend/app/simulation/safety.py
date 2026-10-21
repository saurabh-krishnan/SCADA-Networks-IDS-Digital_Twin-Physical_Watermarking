"""Hard-wired Safety Instrumented System (SIS).

Design rules enforced by construction:
* The SIS has its **own** sensors (separate noise streams) that read the physical
  plant state directly.  It is not attached to the simulated network, so no
  network attack can falsify its inputs, delay its messages or write to it.
* Trips act on the final elements through ``Actuator.trip_override``, which is
  applied *after* any firmware tampering in ``Actuator.step``.
* The attack injector and the response engine are never given a reference to
  this object.  Only the operator (HMI) can reset a latched trip, and only once
  the trip condition has cleared.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.rng import SeedBank
from app.simulation.plant import Plant


@dataclass
class TripRule:
    id: str
    desc: str
    variable: str
    op: str  # ">" or "<"
    limit: float
    sigma: float
    acts: dict  # actuator -> forced output
    condition: str | None = None  # optional permissive (e.g. heater energised)


TRIP_RULES = [
    TripRule("TSHH-101", "Hot-leg temperature high-high", "boiler.T_hl", ">", 540.0, 0.4, {"HTR-101": 0.0}),
    TripRule("PSHH-102", "Cover-gas pressure high-high", "boiler.P_cover", ">", 2.45, 0.004, {"HTR-101": 0.0}),
    TripRule("FSLL-101", "Primary flow low-low (heater energised)", "boiler.m", "<", 6.0, 0.08, {"HTR-101": 0.0},
             condition="heater_on"),
    TripRule("TSHH-401", "Reactor temperature high-high", "mix.T", ">", 85.0, 0.1,
             {"XV-401": 0.0, "XV-402": 0.0, "TCV-401": 100.0}),
    TripRule("LSHH-501", "Tank 501 level high-high", "pipe.L1", ">", 9.8, 0.01, {"XV-501": 0.0}),
    TripRule("LSHH-502", "Tank 502 level high-high", "pipe.L2", ">", 9.8, 0.01, {"XV-502": 0.0}),
]


class SafetySystem:
    def __init__(self, plant: Plant, seeds: SeedBank):
        self._plant = plant
        self._noise = {r.id: seeds.noise(f"sis.{r.id}") for r in TRIP_RULES}
        self.rules = TRIP_RULES
        self.latched: dict[str, dict] = {}
        self.manual_esd = False
        self.history: list[dict] = []
        self.last_values: dict[str, float] = {}

    @property
    def tripped(self) -> bool:
        return bool(self.latched) or self.manual_esd

    def _measure(self, rule: TripRule) -> float:
        v = self._plant.physical[rule.variable] + rule.sigma * self._noise[rule.id].next()
        self.last_values[rule.id] = v
        return v

    def _active(self, rule: TripRule, v: float) -> bool:
        if rule.condition == "heater_on" and self._plant.actuators["HTR-101"].output < 5.0 and rule.id not in self.latched:
            return False
        return v > rule.limit if rule.op == ">" else v < rule.limit

    def evaluate(self, t: float) -> list[dict]:
        new = []
        for rule in self.rules:
            v = self._measure(rule)
            if self._active(rule, v) and rule.id not in self.latched:
                ev = {"t": round(t, 2), "rule": rule.id, "desc": rule.desc, "value": round(v, 3), "limit": rule.limit}
                self.latched[rule.id] = ev
                self.history.append(ev)
                new.append(ev)
        self._apply()
        return new

    def _apply(self) -> None:
        forced: dict[str, float] = {}
        for rid in self.latched:
            rule = next(r for r in self.rules if r.id == rid)
            forced.update(rule.acts)
        if self.manual_esd:
            forced.update({"HTR-101": 0.0, "XV-401": 0.0, "XV-402": 0.0, "P-501": 0.0})
        for a in self._plant.actuators.values():
            a.trip_override = forced.get(a.id)

    def trigger_esd(self, t: float) -> None:
        self.manual_esd = True
        self.history.append({"t": round(t, 2), "rule": "ESD-MANUAL", "desc": "Manual emergency shutdown"})
        self._apply()

    def reset(self, t: float) -> dict:
        """Operator reset. Rules whose condition is still present stay latched."""
        cleared, held = [], []
        for rid in list(self.latched):
            rule = next(r for r in self.rules if r.id == rid)
            v = self.last_values.get(rid, self._measure(rule))
            still = v > rule.limit if rule.op == ">" else v < rule.limit
            if rule.condition == "heater_on":
                still = v < rule.limit
            if still:
                held.append(rid)
            else:
                cleared.append(rid)
                del self.latched[rid]
        self.manual_esd = False
        self._apply()
        return {"cleared": cleared, "still_active": held}

    def to_dict(self) -> dict:
        return {
            "tripped": self.tripped,
            "manual_esd": self.manual_esd,
            "latched": list(self.latched.values()),
            "rules": [{"id": r.id, "desc": r.desc, "limit": r.limit, "op": r.op,
                       "value": round(self.last_values.get(r.id, 0.0), 3),
                       "latched": r.id in self.latched} for r in self.rules],
            "history": self.history[-20:],
            "independent": True,
        }
