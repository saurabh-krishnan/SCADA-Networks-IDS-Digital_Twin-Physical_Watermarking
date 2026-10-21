"""Attack laboratory manager: start/stop scenarios and expose ground-truth labels."""
from __future__ import annotations

from typing import Any, Optional

from app.attacks.context import AttackContext
from app.attacks.scenarios import SCENARIOS, Scenario, catalog


class AttackLab:
    def __init__(self, ctx: AttackContext, seed: int):
        self.ctx = ctx
        self.seed = seed
        self.running: dict[str, Scenario] = {}
        self.history: list[dict] = []
        self._run_seq = 0

    def catalog(self) -> list[dict]:
        return catalog()

    def start(self, key: str, params: Optional[dict[str, Any]], t: float) -> dict:
        if key not in SCENARIOS:
            raise KeyError(f"unknown scenario {key}")
        if key in self.running:
            return {"ok": False, "error": f"{key} already running", "status": self.running[key].status(t)}
        self._run_seq += 1
        scn_seed = self.seed * 1000003 + self._run_seq
        scn = SCENARIOS[key](self.ctx, params or {}, scn_seed)
        scn.start(t)
        self.running[key] = scn
        self.history.append({"run": self._run_seq, "key": key, "t_start": round(t, 2), "seed": scn_seed,
                             "params": scn.params})
        return {"ok": True, "status": scn.status(t)}

    def stop(self, key: str, t: float) -> dict:
        scn = self.running.pop(key, None)
        if scn is None:
            return {"ok": False, "error": f"{key} is not running"}
        scn.stop(t)
        for h in reversed(self.history):
            if h["key"] == key and "t_stop" not in h:
                h["t_stop"] = round(t, 2)
                break
        return {"ok": True, "status": scn.status(t)}

    def stop_all(self, t: float) -> None:
        for key in list(self.running):
            self.stop(key, t)

    def tick(self, t: float, dt: float) -> None:
        for scn in list(self.running.values()):
            scn.tick(t, dt)

    # --------------------------------------------------------------- ground truth
    def active_labels(self, t: float) -> dict[str, dict]:
        """Ground-truth: scenarios whose manipulation is currently in effect.

        Consumed only by the experiment evaluator — never by the detectors.
        """
        return {key: {"category": scn.meta.category, "targets": scn.meta.target_assets}
                for key, scn in self.running.items() if scn.effect_active(t)}

    def any_effect_active(self, t: float) -> bool:
        return any(scn.effect_active(t) for scn in self.running.values())

    def status(self, t: float) -> dict:
        return {
            "running": [scn.status(t) for scn in self.running.values()],
            "catalog": self.catalog(),
            "history": self.history[-40:],
            "ground_truth_active": self.any_effect_active(t),
        }
