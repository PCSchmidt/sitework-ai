"""Fail-fast config loader (docs/06 §7).

All configs in config/*.yaml are validated at startup against these models;
bad config raises immediately rather than failing mid-shift.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class RuleKind(StrEnum):
    ZONE_INTRUSION = "zone_intrusion"
    PROXIMITY = "proximity"
    PPE_ABSENCE = "ppe_absence"
    SPEED = "speed"
    WRONG_WAY = "wrong_way"


class Camera(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    rtsp_url: str
    width: int = 1280
    height: int = 720
    confidence_gate: float = Field(default=0.4, ge=0.0, le=1.0)


class CamerasConfig(BaseModel):
    cameras: list[Camera]


class Zone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    camera_id: str
    # ground-plane polygon in meters, at least 3 points
    polygon_m: list[tuple[float, float]] = Field(min_length=3)
    kind: str = "generic"
    active: bool = True
    min_calibration_quality: float = Field(
        default=2.0, description="hard RMS px gate; metric rules degrade to zone-only above this"
    )


class ZonesConfig(BaseModel):
    zones: list[Zone]


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: RuleKind
    description: str
    zone_ids: list[str] = []
    citation: str | None = None
    radius_m: float | None = Field(default=None, gt=0)
    duration_s: float | None = Field(default=None, gt=0)
    dwell_s: float | None = Field(default=None, gt=0)
    limit_mps: float | None = Field(default=None, gt=0)
    cooldown_s: float = Field(default=120.0, gt=0)

    @model_validator(mode="after")
    def params_match_kind(self) -> Rule:
        required = {
            RuleKind.PROXIMITY: ("radius_m", "duration_s"),
            RuleKind.ZONE_INTRUSION: ("dwell_s",),
            RuleKind.SPEED: ("limit_mps",),
        }.get(self.kind, ())
        missing = [p for p in required if getattr(self, p) is None]
        if missing:
            raise ValueError(f"rule {self.id!r} ({self.kind}) missing params: {missing}")
        return self


class RulesConfig(BaseModel):
    rules: list[Rule]


class ShiftWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    start_local: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_local: str = Field(pattern=r"^\d{2}:\d{2}$")


class ShiftsConfig(BaseModel):
    timezone: str = "UTC"
    shifts: list[ShiftWindow]


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


def load_cameras(path: str = "cameras.yaml") -> CamerasConfig:
    return CamerasConfig.model_validate(_load_yaml(path))


def load_zones(path: str = "zones.yaml") -> ZonesConfig:
    return ZonesConfig.model_validate(_load_yaml(path))


def load_rules(path: str = "rules.yaml") -> RulesConfig:
    return RulesConfig.model_validate(_load_yaml(path))


def load_shifts(path: str = "shifts.yaml") -> ShiftsConfig:
    return ShiftsConfig.model_validate(_load_yaml(path))
