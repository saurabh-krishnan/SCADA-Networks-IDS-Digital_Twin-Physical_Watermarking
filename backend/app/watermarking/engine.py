"""Physical watermarking engine.

Control path:   PLC-1 calls ``offset_for("P-101", t, base)`` every scan and adds the
                returned excitation to the pump command (inside the PLC's secured
                function block).  The actuator and the physical process respond.
Expected path:  two shadow copies of the twin's hydraulics + actuator datasheet
                model are driven with (base + excitation) and (base); their
                difference is the expected watermark response.
Observed path:  SCADA telemetry (FT-101, PT-101), high-pass filtered.
Decision:       ``ChannelEvaluator`` (correlation / gain / SNR) once per second.

Injection is suspended (offset 0) when it would be unsafe or uninformative:
safety-system trip, actuator saturation, process close to an alarm limit,
poor measurement quality, or the configured duration has elapsed.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Optional

from app.core.util import clamp
from app.digital_twin.model import ACTUATOR_DATASHEET, ActuatorModel, HydraulicsModel, TwinParams
from app.watermarking.detector import ChannelEvaluator, DecisionThresholds
from app.watermarking.signal import WatermarkSignal

TARGETS = {"P-101": {"lo": 30.0, "hi": 100.0}, "FCV-101": {"lo": 10.0, "hi": 100.0}}
MAX_AMPLITUDE = 3.0  # % of actuator span — hard bound regardless of configuration


@dataclass
class WatermarkConfig:
    seed: int = 20240607
    amplitude: float = 1.5  # % actuator command
    hold_s: float = 1.0
    mode: str = "prbs"
    target: str = "P-101"
    duration_s: Optional[float] = None
    window_s: float = 20.0
    calib_s: float = 30.0
    hp_tau_s: float = 6.0
    alert_streak: int = 3
    thresholds: DecisionThresholds = field(default_factory=DecisionThresholds)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class _HighPass:
    __slots__ = ("a", "y", "init")

    def __init__(self, tau: float, dt: float):
        self.a = min(1.0, dt / tau)
        self.y = 0.0
        self.init = False

    def __call__(self, x: float) -> float:
        if not self.init:
            self.y, self.init = x, True
        self.y += self.a * (x - self.y)
        return x - self.y


class WatermarkEngine:
    def __init__(self, twin_params: TwinParams, dt: float, config: Optional[WatermarkConfig] = None):
        self.twin_params = twin_params
        self.dt = dt
        self.cfg = config or WatermarkConfig()
        self.enabled = False
        self.t_enabled: Optional[float] = None
        self.injecting = False
        self.suspended_reason: Optional[str] = "disabled"
        self.ctx: dict = {}
        self._applied: float = 0.0  # offset applied at the last PLC scan
        self._applied_prev: float = 0.0
        self.history: deque = deque(maxlen=600)  # (t, offset, e_flow, o_flow, e_p, o_p, valid)
        self.decisions: deque = deque(maxlen=300)
        self.decision = "inactive"
        self.decision_reason = "watermarking disabled"
        self.streak = 0
        self.last_eval_t = -10.0
        self.calibrated_at: Optional[float] = None
        self._build()

    # ------------------------------------------------------------------ setup
    def _build(self) -> None:
        c = self.cfg
        if c.target not in TARGETS:
            raise ValueError(f"target must be one of {list(TARGETS)}")
        if not (0 < c.amplitude <= MAX_AMPLITUDE):
            raise ValueError(f"amplitude must be in (0, {MAX_AMPLITUDE}] %")
        self.signal = WatermarkSignal(c.seed, c.amplitude, c.hold_s, c.mode)
        n = int(round(c.window_s / self.dt))
        self.ch = {"FT-101": ChannelEvaluator("FT-101", n), "PT-101": ChannelEvaluator("PT-101", n)}
        self.shadow_wm: Optional[HydraulicsModel] = None
        self.shadow_base: Optional[HydraulicsModel] = None
        self._act_wm = self._act_base = None
        self._hp = {k: _HighPass(c.hp_tau_s, self.dt) for k in ("e_f", "o_f", "e_p", "o_p")}
        self._shadow_p_wm = self._shadow_p_base = 0.0

    def configure(self, **kw) -> None:
        was = self.enabled
        th = kw.pop("thresholds", None)
        for k, v in kw.items():
            if v is not None and hasattr(self.cfg, k):
                setattr(self.cfg, k, v)
        if th:
            for k, v in th.items():
                setattr(self.cfg.thresholds, k, v)
        self._build()
        if was:
            self.enabled = False
            self.enable(self.ctx.get("t", 0.0))

    def enable(self, t: float) -> None:
        self.enabled = True
        self.t_enabled = t
        self.calibrated_at = None
        for ch in self.ch.values():
            ch.reset(keep_calibration=False)
        self.shadow_wm = self.shadow_base = None
        self._hp = {k: _HighPass(self.cfg.hp_tau_s, self.dt) for k in self._hp}
        self.decision, self.decision_reason, self.streak = "inconclusive", "warming up", 0

    def disable(self, reason: str = "disabled by operator") -> None:
        self.enabled = False
        self.injecting = False
        self.suspended_reason = reason
        self._applied = 0.0
        self.decision, self.decision_reason, self.streak = "inactive", reason, 0

    @property
    def calibrating(self) -> bool:
        if not self.enabled or self.t_enabled is None:
            return False
        return (self.ctx.get("t", 0.0) - self.t_enabled) < self.cfg.calib_s + self.cfg.window_s

    # ------------------------------------------------------------------ control path (PLC-1)
    def offset_for(self, actuator: str, t: float, base: float) -> float:
        if actuator != self.cfg.target:
            return 0.0
        if not self.enabled:
            self.injecting = False
            self._applied = 0.0
            return 0.0
        reason = self._unsafe(t, base)
        self.suspended_reason = reason
        if reason:
            self.injecting = False
            self._applied = 0.0
            return 0.0
        self.injecting = True
        off = self.signal.value(t, self.t_enabled or 0.0)
        lim = TARGETS[actuator]
        off = clamp(base + off, lim["lo"], lim["hi"]) - base
        self._applied = off
        return off

    def _unsafe(self, t: float, base: float) -> Optional[str]:
        c = self.cfg
        ctx = self.ctx
        if c.duration_s is not None and self.t_enabled is not None and t - self.t_enabled > c.duration_s:
            self.disable("configured duration elapsed")
            return "configured duration elapsed"
        if ctx.get("sis_tripped"):
            return "safety system trip / emergency state"
        lim = TARGETS[c.target]
        if base - c.amplitude < lim["lo"] + 1.0 or base + c.amplitude > lim["hi"] - 0.5:
            return "actuator near saturation"
        if ctx.get("flow_local", 20.0) < 13.0:
            return "process near low-flow constraint"
        if ctx.get("thl_local", 450.0) > 475.0:
            return "process near high-temperature constraint"
        if ctx.get("quality_bad_frac", 0.0) > 0.2:
            return "insufficient measurement quality"
        if ctx.get("mode_manual"):
            return "pump not in automatic"
        return None

    # ------------------------------------------------------------------ expected / observed (per tick)
    def update(self, t: float, base_cmd: dict[str, float], obs: dict[str, tuple[float, bool]],
               p_cover_est: float) -> None:
        self.ctx["t"] = t
        applied_prev, self._applied_prev = self._applied_prev, self._applied
        if not self.enabled:
            return
        tgt = self.cfg.target
        speed_base = base_cmd.get("P-101", 85.0)
        valve_base = base_cmd.get("FCV-101", 80.0)
        if self.shadow_wm is None:
            m0 = obs.get("FT-101", (19.5, False))[0]
            self.shadow_wm = HydraulicsModel(self.twin_params, m0)
            self.shadow_base = HydraulicsModel(self.twin_params, m0)
            r, tau = ACTUATOR_DATASHEET[tgt]
            init = speed_base if tgt == "P-101" else valve_base
            self._act_wm = ActuatorModel(init, r, tau)
            self._act_base = ActuatorModel(init, r, tau)
        # the excitation computed at the previous scan acts on the plant during this tick
        cmd_base = speed_base if tgt == "P-101" else valve_base
        a_wm = self._act_wm.step(self.dt, cmd_base + applied_prev)
        a_b = self._act_base.step(self.dt, cmd_base)
        if tgt == "P-101":
            self.shadow_wm.step(self.dt, a_wm, valve_base)
            self.shadow_base.step(self.dt, a_b, valve_base)
            p_wm = self.shadow_wm.p_dis(a_wm, p_cover_est)
            p_b = self.shadow_base.p_dis(a_b, p_cover_est)
        else:
            self.shadow_wm.step(self.dt, speed_base, a_wm)
            self.shadow_base.step(self.dt, speed_base, a_b)
            p_wm = self.shadow_wm.p_dis(speed_base, p_cover_est)
            p_b = self.shadow_base.p_dis(speed_base, p_cover_est)
        e_f = self._hp["e_f"](self.shadow_wm.m - self.shadow_base.m)
        e_p = self._hp["e_p"](p_wm - p_b)
        of, okf = obs.get("FT-101", (float("nan"), False))
        op, okp = obs.get("PT-101", (float("nan"), False))
        o_f = self._hp["o_f"](of) if okf else 0.0
        o_p = self._hp["o_p"](op) if okp else 0.0
        injecting = self.injecting
        self.ch["FT-101"].push(e_f, o_f, okf and injecting)
        self.ch["PT-101"].push(e_p, o_p, okp and injecting)
        self.history.append((round(t, 2), round(applied_prev, 4), round(e_f, 5), round(o_f, 5), round(e_p, 5),
                             round(o_p, 5), bool(okf and injecting)))
        if t - self.last_eval_t >= 1.0 - 1e-9:
            self.last_eval_t = t
            self._evaluate(t)

    def _evaluate(self, t: float) -> None:
        cal = self.calibrating
        res = {name: ch.evaluate(self.cfg.thresholds, cal) for name, ch in self.ch.items()}
        if not cal and self.calibrated_at is None and all(ch.beta0 is not None for ch in self.ch.values()):
            self.calibrated_at = t
        decs = [r["decision"] for r in res.values()]
        if not self.injecting and self.suspended_reason:
            overall, reason = "inconclusive", f"injection suspended: {self.suspended_reason}"
        elif "suspicious" in decs and all(r.get("valid_frac", 0) >= self.cfg.thresholds.min_valid_frac
                                          for r in res.values()):
            overall = "suspicious"
            reason = "; ".join(f"{k}: {r['reason']}" for k, r in res.items() if r["decision"] == "suspicious")
        elif all(d == "consistent" for d in decs):
            overall, reason = "consistent", "observed response matches the watermark on all channels"
        else:
            overall = "inconclusive"
            reason = "; ".join(f"{k}: {r.get('reason', '')}" for k, r in res.items() if r["decision"] != "consistent")
        self.streak = self.streak + 1 if overall == "suspicious" else 0
        self.decision, self.decision_reason = overall, reason
        self.decisions.append({"t": round(t, 2), "decision": overall, "reason": reason, "streak": self.streak,
                               "channels": res})

    @property
    def alarm(self) -> bool:
        return self.enabled and self.decision == "suspicious" and self.streak >= self.cfg.alert_streak

    def to_dict(self, history_n: int = 200) -> dict:
        last = self.decisions[-1] if self.decisions else None
        return {
            "enabled": self.enabled,
            "injecting": self.injecting,
            "suspended_reason": self.suspended_reason if self.enabled else None,
            "config": self.cfg.to_dict(),
            "t_enabled": self.t_enabled,
            "calibrating": self.calibrating,
            "calibrated_at": self.calibrated_at,
            "current_offset": round(self._applied, 4),
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "streak": self.streak,
            "alarm": self.alarm,
            "channels": last["channels"] if last else {},
            "baseline": {k: {"beta0": ch.beta0, "rho0": ch.rho0} for k, ch in self.ch.items()},
            "decisions": list(self.decisions)[-60:],
            "history": [
                {"t": h[0], "offset": h[1], "e_flow": h[2], "o_flow": h[3], "e_p": h[4], "o_p": h[5], "valid": h[6]}
                for h in list(self.history)[-history_n:]
            ],
        }
