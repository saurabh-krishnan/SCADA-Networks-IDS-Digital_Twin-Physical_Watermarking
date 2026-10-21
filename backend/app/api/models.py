"""Pydantic request/response models (validation for every control endpoint)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SpeedRequest(BaseModel):
    speed: float = Field(ge=0.0, le=20.0, description="Simulation speed multiplier (0 = paused)")


class SetpointRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    plc: str
    reg: str = Field(validation_alias="register", serialization_alias="register")
    value: float
    user: str = "operator1"

    @property
    def register(self) -> str:
        return self.reg

    @field_validator("plc", "reg", "user")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class AttackStartRequest(BaseModel):
    scenario: str
    params: dict[str, Any] = Field(default_factory=dict)


class AttackStopRequest(BaseModel):
    scenario: str


class WatermarkConfigRequest(BaseModel):
    amplitude: Optional[float] = Field(default=None, ge=0.1, le=3.0)
    hold_s: Optional[float] = Field(default=None, gt=0.0, le=10.0)
    mode: Optional[str] = None
    target: Optional[str] = None
    seed: Optional[int] = None
    duration_s: Optional[float] = Field(default=None, gt=0.0)

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("prbs", "uniform"):
            raise ValueError("mode must be prbs or uniform")
        return v

    @field_validator("target")
    @classmethod
    def _target(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("P-101", "FCV-101"):
            raise ValueError("target must be P-101 or FCV-101")
        return v


class ResponseModeRequest(BaseModel):
    mode: str

    @field_validator("mode")
    @classmethod
    def _m(cls, v: str) -> str:
        if v not in ("monitor", "approval", "auto"):
            raise ValueError("mode must be monitor|approval|auto")
        return v


class ApproveRequest(BaseModel):
    response_id: str
    operator: str = "operator1"
    approve: bool = True


class MaintenanceRequest(BaseModel):
    enabled: bool


class AckRequest(BaseModel):
    incident_id: str


class ExperimentRunRequest(BaseModel):
    label: Optional[str] = None
    scenario: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    watermark: bool = True
    seed: int = 1337
    attack_at: float = Field(default=60.0, ge=0.0)
    attack_stop: float = Field(default=150.0, gt=0.0)
    duration: float = Field(default=210.0, gt=10.0, le=1200.0)
    response_mode: str = "monitor"
    bin_s: float = Field(default=2.0, gt=0.1, le=10.0)


class SimResetRequest(BaseModel):
    seed: Optional[int] = None
