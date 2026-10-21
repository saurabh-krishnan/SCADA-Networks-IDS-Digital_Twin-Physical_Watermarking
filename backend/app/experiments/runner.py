"""Headless experiment runner.

Runs a fresh, deterministic engine (no live UI) through a scripted timeline:
  [0, attack_at)            baseline + watermark calibration
  [attack_at, attack_stop)  scenario active
  [attack_stop, duration)   recovery
and records a per-sample ground-truth/detection trace. The same trace is scored
under several detector configurations so the comparison is apples-to-apples on a
single run. Predefined comparison modes implement the required experiment matrix.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from app.core.util import now_iso
from app.experiments.metrics import MetricAccumulator, Sample
from app.simulation.engine import EngineConfig, SimulationEngine
from app.watermarking.engine import WatermarkConfig

# detector-configuration variants scored from one recorded trace
CONFIGS = {
    "network_only": {"layers": {"network"}},
    "network_process": {"layers": {"network", "process"}},
    "network_process_twin": {"layers": {"network", "process", "twin"}},
    "full": {"layers": {"network", "process", "twin", "watermark"}},
}


@dataclass
class ExperimentConfig:
    label: str = "experiment"
    seed: int = 1337
    scenario: Optional[str] = None
    scenario_params: dict = field(default_factory=dict)
    watermark: bool = True
    watermark_config: dict = field(default_factory=dict)
    attack_at: float = 60.0
    attack_stop: float = 150.0
    duration: float = 210.0
    response_mode: str = "monitor"
    bin_s: float = 2.0
    deviation_tags: list = field(default_factory=lambda: ["TIC-101.SP"])

    def to_dict(self) -> dict:
        return asdict(self)


def _deviation(engine: SimulationEngine, tags: list[str]) -> dict:
    out = {}
    for reg in tags:
        if reg in engine.scada.approved and reg in engine.scada.tags:
            out[reg] = abs(engine.scada.tags[reg][0] - engine.scada.approved[reg])
    return out


def run_experiment(cfg: ExperimentConfig, progress=None) -> dict:
    t_wall = time.time()
    wm_cfg = WatermarkConfig(**cfg.watermark_config) if cfg.watermark_config else WatermarkConfig()
    econf = EngineConfig(seed=cfg.seed, watermark=wm_cfg, record_traffic=False)
    eng = SimulationEngine(econf)
    if cfg.watermark:
        eng.watermark.enable(eng.t)
    eng.response.set_mode(cfg.response_mode)
    acc_full = MetricAccumulator(bin_s=cfg.bin_s, layers=None, deviation_tags=cfg.deviation_tags)
    scenario_started = False
    scenario_stopped = False
    dt = eng.cfg.dt
    n = int(cfg.duration / dt)
    base_t = eng.t
    for i in range(n):
        show = eng.t - base_t
        if cfg.scenario and not scenario_started and show >= cfg.attack_at:
            eng.lab.start(cfg.scenario, cfg.scenario_params, eng.t)
            scenario_started = True
        if cfg.scenario and scenario_started and not scenario_stopped and show >= cfg.attack_stop:
            eng.lab.stop(cfg.scenario, eng.t)
            scenario_stopped = True
        eng._tick(record=False)
        labels = eng.lab.active_labels(eng.t)
        gt_zones = set()
        for lab in labels.values():
            for a in lab["targets"]:
                gt_zones.add(_zone_of_asset(a))
        active_findings = [f for f in eng.ids.findings.active.values() if f.severity != "info"]
        acc_full.record(Sample(
            t=eng.t - base_t,
            gt_active=bool(labels),
            gt_zones=gt_zones,
            alert_assets={f.asset for f in active_findings},
            alert_layers={f.layer for f in active_findings},
            deviation=_deviation(eng, cfg.deviation_tags),
            incident_open=any(inc.status not in ("resolved",) for inc in eng.ids.correlation.incidents.values()),
        ))
        if progress and i % 200 == 0:
            progress(i / n)
    # score under each detector configuration from the one recorded trace
    variants = {}
    for name, c in CONFIGS.items():
        acc = MetricAccumulator(bin_s=cfg.bin_s, layers=c["layers"], deviation_tags=cfg.deviation_tags)
        acc.samples = acc_full.samples
        variants[name] = acc.compute().to_dict()
    overall = acc_full.compute().to_dict()
    return {
        "label": cfg.label, "config": cfg.to_dict(), "created": now_iso(),
        "wall_time_s": round(time.time() - t_wall, 2),
        "sim_duration_s": cfg.duration, "samples": len(acc_full.samples),
        "overall": overall, "by_detector_config": variants,
        "scenario": cfg.scenario, "watermark": cfg.watermark,
        "attack_window": [cfg.attack_at, cfg.attack_stop],
        "final_incidents": eng.ids.incidents(limit=10),
        "responses": [r for r in eng.response.history if r.get("status") == "executed"],
    }


def _zone_of_asset(a: str) -> str:
    from app.ids.correlation import PREFIX_ZONE, ZONE
    if a in ZONE:
        return ZONE[a]
    tail = a.split("-")[-1]
    if tail[:1].isdigit() and tail[:1] in PREFIX_ZONE and len(tail) == 3:
        return PREFIX_ZONE[tail[:1]]
    return "network"


# ---------------------------------------------------------------------------
# Predefined comparison suite (the required experiment matrix A–F).
# ---------------------------------------------------------------------------
def comparison_suite(scenario: str = "false_data_injection", seed: int = 1337,
                     params: Optional[dict] = None) -> ExperimentConfig:
    return ExperimentConfig(label=f"suite:{scenario}", seed=seed, scenario=scenario, scenario_params=params or {},
                            watermark=True)


SUITE_PRESETS = {
    "A_normal": ExperimentConfig(label="A. Normal operation", scenario=None, watermark=True),
    "B_attack_no_wm": ExperimentConfig(label="B. Attack, watermark OFF", scenario="false_data_injection",
                                       watermark=False),
    "C_attack_wm": ExperimentConfig(label="C. Attack, watermark ON", scenario="watermark_interference",
                                    watermark=True),
}
