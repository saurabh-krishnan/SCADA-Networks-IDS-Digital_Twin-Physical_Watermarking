"""Multi-layer IDS orchestration."""
from __future__ import annotations

from app.ids.base import LAYERS, FindingManager
from app.ids.correlation import CorrelationEngine
from app.ids.network_detector import NetworkDetector
from app.ids.process_detector import ProcessDetector
from app.ids.twin_detector import TwinDetector
from app.ids.watermark_detector import WatermarkDetector


class IDS:
    def __init__(self, network: NetworkDetector, process: ProcessDetector, twin: TwinDetector,
                 watermark: WatermarkDetector):
        self.network = network
        self.process = process
        self.twin = twin
        self.watermark = watermark
        self.findings = FindingManager()
        self.correlation = CorrelationEngine()
        self.enabled = {layer: True for layer in LAYERS}
        self._last_wm = -10.0
        self.raised_log: list = []

    def step(self, t: float, scada, approved: dict[str, float]) -> list:
        conds = []
        net = self.network.process(t)  # always consume the SPAN queue
        if self.enabled["network"]:
            conds += net
        proc = self.process.evaluate(t, scada, approved)  # keeps windows/consistency up to date
        if self.enabled["process"]:
            conds += proc
        if self.enabled["twin"]:
            conds += self.twin.evaluate(t)
        if self.enabled["watermark"] and t - self._last_wm >= 0.5:
            self._last_wm = t
            conds += self.watermark.evaluate(t)
        for c in conds:
            self.findings.report(t, c)
        self.findings.sweep(t)
        events = self.findings.drain()
        self.correlation.ingest(t, events, self.findings.by_id)
        return events

    def alerts(self, limit: int = 200, active_only: bool = False) -> list[dict]:
        fs = self.findings.all
        if active_only:
            fs = [f for f in fs if f.active]
        return [f.to_dict() for f in fs[-limit:]][::-1]

    def incidents(self, limit: int = 50) -> list[dict]:
        incs = sorted(self.correlation.incidents.values(), key=lambda i: -i.updated)
        return [i.to_dict() for i in incs[:limit]]
