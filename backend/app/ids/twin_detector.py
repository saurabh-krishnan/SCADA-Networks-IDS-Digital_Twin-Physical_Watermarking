"""Digital-twin layer: persistent / sudden residuals and correlated anomalies.

Classification hint: if the measurements are mutually consistent (energy
balances and redundancy hold) but disagree with the twin, the likely cause is a
model mismatch / unmodelled process change; otherwise the measurements
themselves are inconsistent with physics (possible falsification).
"""
from __future__ import annotations

from app.digital_twin.prediction import DigitalTwin
from app.ids.base import Condition
from app.ids.consistency import BoilerConsistency

ASSET = {"TT-101": "TT-101", "TT-102": "TT-102", "TT-103": "TT-103", "FT-101": "FT-101", "PT-101": "PT-101",
         "PT-102": "PT-102", "TT-201": "TT-201", "TT-202": "TT-202", "FT-201": "FT-201"}


class TwinDetector:
    LAYER = "twin"

    def __init__(self, twin: DigitalTwin, consistency: BoilerConsistency):
        self.twin = twin
        self.consistency = consistency

    def evaluate(self, t: float) -> list[Condition]:
        out: list[Condition] = []
        tw = self.twin
        if not tw.initialized:
            return out
        alarmed = []
        for tag, tr in tw.trackers.items():
            if tr.calibrating or not tr.valid:
                continue
            ev = {"tag": tag, "observed": round(tr.obs, 4), "predicted": round(tr.pred, 4),
                  "residual": round(tr.r, 4), "z": round(tr.z, 2), "sigma": round(tr.sigma, 4),
                  "cusum": round(tr.cusum, 2), "alarm_since": tr.alarm_since,
                  "persistence_s": round(t - tr.alarm_since, 1) if tr.alarm_since is not None else 0.0,
                  "twin_gated": tw.gated.get(tag, False)}
            if tr.sudden:
                alarmed.append(tag)
                out.append(Condition(self.LAYER, "TWIN-SUDDEN", ASSET[tag], "high", "Sudden prediction error",
                                     ev, min(1.0, abs(tr.z) / 20.0), 0.8,
                                     "Cross-check sensor against twin estimate; mark suspicious", hold_s=4.0))
            elif tr.persistent:
                alarmed.append(tag)
                out.append(Condition(self.LAYER, "TWIN-PERSIST", ASSET[tag], "medium",
                                     "Persistent residual (inconsistent with twin)", ev, tr.score, 0.7,
                                     "Investigate sensor / process; compare redundant instruments", hold_s=4.0))
        if len(alarmed) >= 2:
            consistent = self.consistency.consistent()
            hint = ("model mismatch / unmodelled process change (measurements mutually consistent)" if consistent
                    else "measurements inconsistent with the physics model (possible falsification)")
            out.append(Condition(self.LAYER, "TWIN-CORRELATED", "boiler-loop", "high" if not consistent else "medium",
                                 "Correlated multi-sensor anomaly",
                                 {"tags": alarmed, "measurements_self_consistent": consistent, "hypothesis": hint,
                                  "model_confidence": round(tw.confidence, 3), "sync_status": tw.sync_status,
                                  **self.consistency.to_dict()},
                                 min(1.0, len(alarmed) / 4.0), 0.75,
                                 "Resynchronise / recalibrate twin" if consistent else
                                 "Treat affected telemetry as untrusted; fail over to secure channel", hold_s=5.0))
        return out
