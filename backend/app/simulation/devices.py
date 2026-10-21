"""Reusable field-device abstractions: sensors, actuators and the device registry.

Separation of concerns that the whole platform relies on:

* ``Sensor.sample(true_value)`` turns *physical* state into a *measurement*
  (noise, quantisation, range clamp).  The physical state itself is never
  modified by a sensor.
* ``Sensor.output_hook`` / ``Actuator.firmware_hook`` are the only places where
  the attack laboratory can tamper with a field device ("compromised firmware").
  They are plain attributes so the attack injector never needs a reference to
  the plant model, the safety system or the digital twin.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.core.rng import NoiseStream
from app.core.util import clamp, r


@dataclass
class AlarmLimits:
    lo_lo: Optional[float] = None
    lo: Optional[float] = None
    hi: Optional[float] = None
    hi_hi: Optional[float] = None

    def classify(self, v: float) -> str:
        if self.hi_hi is not None and v >= self.hi_hi:
            return "critical"
        if self.lo_lo is not None and v <= self.lo_lo:
            return "critical"
        if self.hi is not None and v >= self.hi:
            return "alarm"
        if self.lo is not None and v <= self.lo:
            return "alarm"
        return "normal"

    def to_dict(self) -> dict:
        return {"lo_lo": self.lo_lo, "lo": self.lo, "hi": self.hi, "hi_hi": self.hi_hi}


@dataclass
class Device:
    id: str
    name: str
    dtype: str = "device"  # sensor | actuator | plc | rtu | server | workstation | gateway | switch | ids | broker
    subsystem: str = ""
    controller: Optional[str] = None  # owning PLC / RTU id
    mode: str = "auto"  # auto | manual | maintenance | offline
    state: str = "running"
    comm_status: str = "online"  # online | degraded | offline | quarantined
    alarm_state: str = "normal"  # normal | warning | alarm | critical
    auth_state: str = "n/a"
    suspicious: bool = False
    quarantined: bool = False
    params: dict[str, Any] = field(default_factory=dict)

    def base_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.dtype,
            "subsystem": self.subsystem,
            "controller": self.controller,
            "mode": self.mode,
            "state": self.state,
            "comm_status": "quarantined" if self.quarantined else self.comm_status,
            "alarm_state": self.alarm_state,
            "auth_state": self.auth_state,
            "suspicious": self.suspicious,
            "quarantined": self.quarantined,
            "params": self.params,
        }


@dataclass
class Sensor(Device):
    variable: str = ""
    unit: str = ""
    noise_sigma: float = 0.0
    resolution: float = 0.01
    range_lo: float = 0.0
    range_hi: float = 100.0
    limits: AlarmLimits = field(default_factory=AlarmLimits)
    max_rate: float = 1e9  # physically plausible max |dx/dt| (units/s, 1-s averages)
    sample_every: int = 1  # ticks between field reports
    noise: Optional[NoiseStream] = None
    last_value: float = 0.0
    last_true: float = 0.0
    output_hook: Optional[Callable[[float, float], float]] = None  # (t, value) -> value

    def __post_init__(self):
        self.dtype = "sensor"

    def sample(self, t: float, true_value: float) -> float:
        self.last_true = true_value
        v = true_value
        if self.noise is not None and self.noise_sigma > 0:
            v += self.noise_sigma * self.noise.next()
        v = clamp(v, self.range_lo, self.range_hi)
        if self.resolution > 0:
            v = round(v / self.resolution) * self.resolution
        if self.output_hook is not None:
            v = self.output_hook(t, v)
        self.last_value = v
        return v

    def to_dict(self) -> dict:
        d = self.base_dict()
        d.update(
            variable=self.variable,
            unit=self.unit,
            noise_sigma=self.noise_sigma,
            range=[self.range_lo, self.range_hi],
            limits=self.limits.to_dict(),
            field_value=r(self.last_value, 3),
        )
        return d


@dataclass
class Actuator(Device):
    kind: str = "valve"  # pump_vfd | valve | heater | fan | onoff_valve | dosing_pump | motor_vfd
    unit: str = "%"
    lo: float = 0.0
    hi: float = 100.0
    rate_limit: float = 1e9  # units per second
    tau: float = 0.0  # first-order lag (s)
    command: float = 0.0
    output: float = 0.0
    feedback: float = 0.0
    trip_override: Optional[float] = None  # set only by the hard-wired safety system
    firmware_hook: Optional[dict] = None  # set only by the attack laboratory

    def __post_init__(self):
        self.dtype = "actuator"

    def set_command(self, value: float) -> None:
        self.command = clamp(value, self.lo, self.hi)

    def step(self, dt: float) -> None:
        target = self.command
        hook = self.firmware_hook
        if hook:
            if hook.get("stuck") is not None:
                target = hook["stuck"]
            else:
                target = target * hook.get("scale", 1.0) + hook.get("offset", 0.0)
        target = clamp(target, self.lo, self.hi)
        # Safety interlock acts downstream of (and independent from) any firmware tampering:
        # it models a hard-wired trip relay that de-energises the final element *immediately*,
        # bypassing the normal control-move rate limit and actuator lag.
        if self.trip_override is not None:
            self.output = clamp(self.trip_override, self.lo, self.hi)
            self.feedback = self.output
            return
        if self.tau > 0:
            desired = self.output + (target - self.output) * min(1.0, dt / self.tau)
        else:
            desired = target
        max_step = self.rate_limit * dt
        delta = clamp(desired - self.output, -max_step, max_step)
        self.output = clamp(self.output + delta, self.lo, self.hi)
        if hook and hook.get("report_command"):
            self.feedback = self.command  # deceptive firmware reports what was asked for
        else:
            self.feedback = self.output

    def to_dict(self) -> dict:
        d = self.base_dict()
        d.update(
            kind=self.kind,
            unit=self.unit,
            range=[self.lo, self.hi],
            command=r(self.command, 3),
            output=r(self.output, 3),
            feedback=r(self.feedback, 3),
            tripped=self.trip_override is not None,
        )
        return d


class DeviceRegistry:
    def __init__(self) -> None:
        self.devices: dict[str, Device] = {}

    def add(self, dev: Device) -> Device:
        if dev.id in self.devices:
            raise ValueError(f"duplicate device id {dev.id}")
        self.devices[dev.id] = dev
        return dev

    def get(self, dev_id: str) -> Device:
        return self.devices[dev_id]

    def __contains__(self, dev_id: str) -> bool:
        return dev_id in self.devices

    @property
    def sensors(self) -> list[Sensor]:
        return [d for d in self.devices.values() if isinstance(d, Sensor)]

    @property
    def actuators(self) -> list[Actuator]:
        return [d for d in self.devices.values() if isinstance(d, Actuator)]

    def to_list(self) -> list[dict]:
        out = []
        for d in self.devices.values():
            out.append(d.to_dict() if hasattr(d, "to_dict") else d.base_dict())
        return out
