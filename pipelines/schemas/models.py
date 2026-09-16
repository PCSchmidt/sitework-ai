"""Event schemas per docs/06-schemas-and-api.md.

Everything crossing a process boundary (fast path → broker → slow path → DB) is one of
these models. JSON Schema is exported to schemas/ for the TS dashboard.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

# Band-3 recomputation tolerances (docs/06 §3 — normative, do not diverge).
DISTANCE_TOL_M = 0.15
VELOCITY_TOL_MPS = 0.2
TIME_TOL_S = 0.2
RELATIVE_TOL = 0.05

# Hard calibration gate (docs/04 §3): valid = rms_px <= RMS_GATE_PX
RMS_GATE_PX = 2.0


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Classification(StrEnum):
    NORMAL_OPS = "normal_ops"
    NEAR_MISS = "near_miss"
    VIOLATION = "violation"
    FALSE_POSITIVE = "false_positive"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalibrationQuality(_Base):
    rms_px: float = Field(ge=0)
    valid: bool

    @classmethod
    def from_rms(cls, rms_px: float) -> CalibrationQuality:
        return cls(rms_px=rms_px, valid=rms_px <= RMS_GATE_PX)


class TrackState(_Base):
    cov_trace: float = Field(ge=0)
    age_frames: int = Field(ge=0)
    hits: int = Field(ge=0)


class PPEState(_Base):
    helmet: bool | None = None
    vest: bool | None = None


class Track(_Base):
    track_id: int
    cls: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox_px: tuple[float, float, float, float]
    ground_point_m: tuple[float, float] | None = None
    velocity_mps: tuple[float, float] | None = None
    speed_mps: float | None = Field(default=None, ge=0.0)
    state: TrackState
    zone_ids: list[str] = []
    ppe: PPEState = PPEState()


class TrackletFrame(_Base):
    """Fast path → broker, ~10 Hz/camera (docs/06 §1)."""

    schema_version: str = SCHEMA_VERSION
    camera_id: str
    frame_ts: float
    seq: int = Field(ge=0)
    calibration_quality: CalibrationQuality
    tracks: list[Track] = []


class TriggerMetrics(_Base):
    min_distance_m: float | None = Field(default=None, ge=0.0)
    duration_s: float | None = Field(default=None, ge=0.0)
    closing_speed_mps: float | None = None


class TriggerEvent(_Base):
    """Fast path → agent queue (docs/06 §2)."""

    schema_version: str = SCHEMA_VERSION
    event_id: str
    trigger_ts: float
    camera_id: str
    rule_id: str
    severity_hint: Severity
    metrics: TriggerMetrics = TriggerMetrics()
    involved_track_ids: list[int]
    track_window_ref: str
    clip_ref: str | None = None
    cooldown_key: str
    calibration_quality: CalibrationQuality


class KinematicsVerdict(_Base):
    """Agent output — verified kinematics (docs/06 §3)."""

    verified_min_distance_m: float | None = Field(default=None, ge=0.0)
    closing_velocity_mps: float | None = None
    ttc_s: float | None = Field(default=None, ge=0.0)
    classification: Classification
    recompute_inputs: dict[str, str] = {}


class AgentRunStats(_Base):
    model: str
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    turns: int = Field(ge=0)
    wall_ms: int = Field(ge=0)


class IncidentRecord(_Base):
    """Slow path → Band-3 gate → DB (docs/06 §3)."""

    schema_version: str = SCHEMA_VERSION
    event_id: str
    camera_id: str
    trigger_ts: float
    severity: Severity
    classification: Classification
    verified_kinematics: KinematicsVerdict
    narrative_md: str = ""
    rule_citations: list[str] = []
    recommended_actions: list[str] = []
    evidence_refs: list[str] = []
    agent_run: AgentRunStats | None = None


class Band3Tolerance(_Base):
    """Serialized copy of the normative gate constants (docs/06 §3)."""

    distance_m: float = DISTANCE_TOL_M
    velocity_mps: float = VELOCITY_TOL_MPS
    time_s: float = TIME_TOL_S
    relative: float = RELATIVE_TOL
