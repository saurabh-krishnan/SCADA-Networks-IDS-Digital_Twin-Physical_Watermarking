"""Ground-truth labelling and detection metrics for reproducible experiments.

Labelling (per evaluation window of ``bin_s`` seconds, aligned to the run):
* a window is a POSITIVE if the attack's ``effect_active`` was true for at least
  ``min_overlap`` of it (ground truth from the attack lab),
* a window is DETECTED if the IDS held >=1 non-info finding whose asset/zone maps
  to the attacked zone during the window (optionally restricted to a layer set,
  to compare detector configurations).

From the confusion matrix we report precision/recall/F1, plus detection latency
(first detection after effect onset), process deviation (RMS of the controlled
variable from its approved setpoint) and recovery time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def _zone(asset: str) -> str:
    from app.ids.correlation import PREFIX_ZONE, ZONE
    if asset in ZONE:
        return ZONE[asset]
    tail = asset.split("-")[-1]
    if tail[:1].isdigit() and tail[:1] in PREFIX_ZONE and len(tail) == 3:
        return PREFIX_ZONE[tail[:1]]
    return "network"


@dataclass
class Sample:
    t: float
    gt_active: bool
    gt_zones: set
    alert_assets: set  # assets with an active non-info finding this sample
    alert_layers: set
    deviation: dict  # register -> |reported - approved|
    incident_open: bool


@dataclass
class MetricResult:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    detection_latency_s: float | None = None
    windows: int = 0
    attack_windows: int = 0
    process_deviation_rms: float = 0.0
    process_deviation_max: float = 0.0
    recovery_time_s: float | None = None
    detected: bool = False

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


class MetricAccumulator:
    def __init__(self, bin_s: float = 1.0, min_overlap: float = 0.5, layers: set | None = None,
                 deviation_tags: list[str] | None = None, incident_only: bool = False):
        self.bin_s = bin_s
        self.min_overlap = min_overlap
        self.layers = layers  # None = all layers
        self.deviation_tags = deviation_tags or ["TIC-101.SP"]
        self.incident_only = incident_only
        self.samples: list[Sample] = []

    def record(self, s: Sample) -> None:
        self.samples.append(s)

    def compute(self) -> MetricResult:
        if not self.samples:
            return MetricResult()
        res = MetricResult()
        bins: dict[int, list[Sample]] = {}
        t0 = self.samples[0].t
        for s in self.samples:
            bins.setdefault(int((s.t - t0) // self.bin_s), []).append(s)
        onset_t = next((s.t for s in self.samples if s.gt_active), None)
        first_detect_t = None
        dev_sq = []
        dev_max = 0.0
        for s in self.samples:
            for tag, d in s.deviation.items():
                dev_sq.append(d * d)
                dev_max = max(dev_max, d)
        for idx in sorted(bins):
            win = bins[idx]
            frac_active = sum(1 for s in win if s.gt_active) / len(win)
            positive = frac_active >= self.min_overlap
            gt_zones = set().union(*[s.gt_zones for s in win]) if any(s.gt_zones for s in win) else set()
            detected = False
            detect_t = None
            for s in win:
                layers = s.alert_layers if self.layers is None else (s.alert_layers & self.layers)
                if not layers:
                    continue
                if self.incident_only and not s.incident_open:
                    continue
                hit_zones = {_zone(a) for a in s.alert_assets}
                if not gt_zones or hit_zones & gt_zones or (positive and s.alert_assets):
                    detected = True
                    detect_t = s.t
                    break
            res.windows += 1
            if positive:
                res.attack_windows += 1
                if detected:
                    res.tp += 1
                    if first_detect_t is None:
                        first_detect_t = detect_t
                else:
                    res.fn += 1
            else:
                if detected:
                    res.fp += 1
                else:
                    res.tn += 1
        res.precision = res.tp / (res.tp + res.fp) if (res.tp + res.fp) else (1.0 if res.attack_windows == 0 else 0.0)
        res.recall = res.tp / (res.tp + res.fn) if (res.tp + res.fn) else 1.0
        res.f1 = (2 * res.precision * res.recall / (res.precision + res.recall)
                  if (res.precision + res.recall) else 0.0)
        res.detected = res.tp > 0
        if onset_t is not None and first_detect_t is not None:
            # clamp to 0: detection landing in the window that straddles the onset is
            # "detected within the first window", not negative latency (a bin-alignment artifact)
            res.detection_latency_s = round(max(0.0, first_detect_t - onset_t), 2)
        res.process_deviation_rms = math.sqrt(sum(dev_sq) / len(dev_sq)) if dev_sq else 0.0
        res.process_deviation_max = dev_max
        # recovery: time from last GT-active sample to the deviation falling back under tolerance and staying there
        last_active = next((s.t for s in reversed(self.samples) if s.gt_active), None)
        if last_active is not None:
            tol = 0.5
            rec = None
            for s in self.samples:
                if s.t < last_active:
                    continue
                if all(d <= tol for d in s.deviation.values()):
                    rec = s.t
                    break
            if rec is not None:
                res.recovery_time_s = round(rec - last_active, 2)
        return res
