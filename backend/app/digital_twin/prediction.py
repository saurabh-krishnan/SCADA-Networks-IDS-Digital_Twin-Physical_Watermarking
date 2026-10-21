"""Digital-twin service: independent state estimation, prediction and residuals.

Each tick:
 1. propagate the twin's *own* state with its RK4 model and its own actuator
    models, driven by issued commands (+ trusted watermark offsets) and measured
    inputs (heater power, fan speed, generator power);
 2. compute residuals of every monitored measurement against the *prior*
    (one-step-ahead) prediction;
 3. apply a small, *gated* correction toward measurements whose normalised
    innovation is inside the gate — falsified readings that jump outside the gate
    are rejected and the twin keeps evolving on physics alone.

The twin never touches the simulator's ground truth.  Falsified telemetry can
influence it only through the gated correction, and only by staying within the
gate (a slow, "stealthy" ramp) — a limitation that is visible in experiments.
"""
from __future__ import annotations

from collections import deque
from typing import Optional

from app.digital_twin.model import (ACTUATOR_DATASHEET, MEASUREMENT_STATE, ActuatorModel, TwinParams,
                                    TwinPhysics)
from app.digital_twin.residuals import ResidualConfig, ResidualTracker

MONITORED = ["TT-101", "TT-102", "TT-103", "FT-101", "PT-101", "PT-102", "TT-201", "TT-202", "FT-201"]

# residual sigma = sqrt(sensor_sigma^2 + model_sigma^2), configured per variable
DEFAULT_SIGMA = {
    "TT-101": 0.7, "TT-102": 0.7, "TT-103": 0.6, "FT-101": 0.12, "PT-101": 0.03, "PT-102": 0.008,
    "TT-201": 0.7, "TT-202": 0.7, "FT-201": 0.08,
}

PARAM_NODES = {
    "ns=3;s=Twin.HX.UA_SCALE": "hx_scale",
    "ns=3;s=Twin.Boiler.UA_LOSS": "ua_loss",
    "ns=3;s=Twin.Pump.H0": "pump_h0",
}


class DigitalTwin:
    def __init__(self, params: Optional[TwinParams] = None, gate_z: float = 5.0, tau_corr: float = 6.0,
                 res_cfg: Optional[ResidualConfig] = None):
        self.params = params or TwinParams()
        self.phys = TwinPhysics(self.params)
        self.gate_z = gate_z
        self.tau_corr = tau_corr
        self.res_cfg = res_cfg or ResidualConfig()
        self.trackers = {tag: ResidualTracker(tag, DEFAULT_SIGMA[tag], self.res_cfg) for tag in MONITORED}
        self.act = {aid: ActuatorModel(0.0, *ACTUATOR_DATASHEET[aid]) for aid in ACTUATOR_DATASHEET}
        self.initialized = False
        self.pred: dict[str, float] = {}
        self.gated: dict[str, bool] = {tag: False for tag in MONITORED}
        self.gated_since: dict[str, Optional[float]] = {tag: None for tag in MONITORED}
        self.forecast: list[dict] = []
        self._last_forecast = -10.0
        self._prev_cmd: Optional[dict] = None
        self.last_inputs: dict[str, float] = {}
        self.confidence = 1.0
        self.health = "initialising"
        self.sync_status = "not synchronised"
        self._z2: deque = deque(maxlen=100)
        self.config_log: list[dict] = []
        self.resyncs = 0
        self.t = 0.0

    # ------------------------------------------------------------------ sync
    def synchronize(self, obs: dict[str, float], cmd: dict[str, float], t: float, reason: str = "initial") -> None:
        """(Re)initialise the state from observations — an explicit, logged event."""
        x = self.phys.x
        for tag, sk in MEASUREMENT_STATE.items():
            if sk and tag in obs:
                x[sk] = obs[tag]
        for aid, a in self.act.items():
            a.value = cmd.get(aid, a.value)
        for tr in self.trackers.values():
            tr.reset(keep_calibration=self.initialized)
        self.gated = {tag: False for tag in MONITORED}
        self.gated_since = {tag: None for tag in MONITORED}
        self._prev_cmd = dict(cmd)
        self.initialized = True
        self.resyncs += 1 if reason != "initial" else 0
        self.config_log.append({"t": round(t, 2), "event": "synchronize", "reason": reason})

    # ------------------------------------------------------------------ main step
    def step(self, t: float, dt: float, cmd: dict[str, float], measured_inputs: dict[str, float],
             obs: dict[str, tuple[float, bool]]) -> None:
        self.t = t
        if not self.initialized:
            good = {k: v for k, (v, ok) in obs.items() if ok}
            if all(k in good for k in ("TT-101", "TT-102", "TT-103", "FT-101", "TT-201", "TT-202", "FT-201")):
                self.synchronize(good, cmd, t)
            return
        prev = self._prev_cmd or cmd
        u_act = {aid: self.act[aid].step(dt, prev.get(aid, self.act[aid].value)) for aid in self.act}
        self._prev_cmd = dict(cmd)
        u = {
            "pump_pct": u_act["P-101"], "valve_pct": u_act["FCV-101"], "pump2_pct": u_act["P-201"],
            "heater_kw": measured_inputs.get("heater_kw", self.last_inputs.get("heater_kw", 0.0)),
            "fan_pct": measured_inputs.get("fan_pct", self.last_inputs.get("fan_pct", 40.0)),
            "gen_kw": measured_inputs.get("gen_kw", self.last_inputs.get("gen_kw", 300.0)),
        }
        self.last_inputs = u
        self.phys.x = self.phys.rk4(self.phys.x, u, dt)
        pred = self.phys.outputs(self.phys.x, u)
        self.pred = pred
        k = min(1.0, dt / self.tau_corr)
        z2 = []
        for tag in MONITORED:
            tr = self.trackers[tag]
            val, ok = obs.get(tag, (float("nan"), False))
            tr.update(t, val, pred[tag], ok)
            if not ok:
                continue
            z2.append(min(tr.z * tr.z, 100.0))
            sk = MEASUREMENT_STATE[tag]
            inside = abs(tr.z) < self.gate_z
            if inside:
                self.gated[tag] = False
                self.gated_since[tag] = None
                if sk:
                    self.phys.x[sk] += k * (val - pred[tag])
            else:
                if not self.gated[tag]:
                    self.gated_since[tag] = t
                self.gated[tag] = True
        if z2:
            self._z2.append(sum(z2) / len(z2))
        self._update_health()
        if t - self._last_forecast >= 1.0:
            self._last_forecast = t
            self.forecast = self._forecast(u, horizon=20.0, h=0.5)

    def _update_health(self) -> None:
        if not self._z2:
            return
        rms = (sum(self._z2) / len(self._z2)) ** 0.5
        self.confidence = max(0.0, min(1.0, 1.0 - (rms - 1.0) / 4.0))
        self.health = "healthy" if self.confidence > 0.7 else "degraded" if self.confidence > 0.4 else "poor"
        n_g = sum(1 for v in self.gated.values() if v)
        if any(tr.calibrating for tr in self.trackers.values()):
            self.sync_status = "calibrating"
        elif n_g == 0:
            self.sync_status = "synchronised"
        elif n_g < len(MONITORED) / 2:
            self.sync_status = f"partially gated ({n_g} rejected)"
        else:
            self.sync_status = "diverged"

    def _forecast(self, u: dict, horizon: float, h: float) -> list[dict]:
        x = dict(self.phys.x)
        out = []
        steps = int(horizon / h)
        for i in range(1, steps + 1):
            x = self.phys.rk4(x, u, h)
            y = self.phys.outputs(x, u)
            out.append({"dt": round(i * h, 2), "TT-101": round(y["TT-101"], 3), "TT-102": round(y["TT-102"], 3),
                        "FT-101": round(y["FT-101"], 4), "TT-201": round(y["TT-201"], 3)})
        return out

    # ------------------------------------------------------------------ configuration (via TWIN-01)
    def apply_config(self, node_id: str, value: float, src: str, user: Optional[str], t: float) -> bool:
        attr = PARAM_NODES.get(node_id)
        ok = attr is not None and src == "EWS-01" and 0.2 <= float(value) <= 5.0 if attr == "hx_scale" else (
            attr is not None and src == "EWS-01")
        if ok:
            if attr == "hx_scale":
                old = self.phys.hx_scale
                self.phys.hx_scale = float(value)
            else:
                old = getattr(self.params, attr)
                setattr(self.params, attr, float(value))
            self.config_log.append({"t": round(t, 2), "event": "config_write", "node": node_id, "old": old,
                                    "value": value, "src": src, "user": user})
        else:
            self.config_log.append({"t": round(t, 2), "event": "config_write_rejected", "node": node_id,
                                    "value": value, "src": src, "user": user})
        return ok

    # ------------------------------------------------------------------ views
    def anomaly_score(self) -> float:
        return max((tr.score for tr in self.trackers.values() if not tr.calibrating), default=0.0)

    def to_dict(self) -> dict:
        return {
            "initialized": self.initialized,
            "state": {k: round(v, 4) for k, v in self.phys.x.items()},
            "predictions": {k: round(v, 4) for k, v in self.pred.items()},
            "residuals": {tag: tr.to_dict() for tag, tr in self.trackers.items()},
            "gated": dict(self.gated),
            "confidence": round(self.confidence, 3),
            "health": self.health,
            "sync_status": self.sync_status,
            "anomaly_score": round(self.anomaly_score(), 3),
            "inputs": {k: round(v, 3) for k, v in self.last_inputs.items()},
            "forecast": self.forecast,
            "params": {**self.params.to_dict(), "hx_scale": self.phys.hx_scale},
            "config_log": self.config_log[-10:],
            "resyncs": self.resyncs,
            "gate_z": self.gate_z,
            "tau_corr_s": self.tau_corr,
            "independent_of_ground_truth": True,
        }
