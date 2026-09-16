"""Schema round-trip tests — M0 exit criterion."""

from __future__ import annotations

from pipelines.schemas import (
    SCHEMA_VERSION,
    CalibrationQuality,
    Classification,
    IncidentRecord,
    KinematicsVerdict,
    Severity,
    TrackletFrame,
    TriggerEvent,
)
from pipelines.schemas.models import RMS_GATE_PX


def sample_tracklet_frame() -> TrackletFrame:
    return TrackletFrame.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "camera_id": "dock_north_01",
            "frame_ts": 1789502400.12,
            "seq": 84213,
            "calibration_quality": {"rms_px": 1.4, "valid": True},
            "tracks": [
                {
                    "track_id": 42,
                    "cls": "forklift",
                    "confidence": 0.91,
                    "bbox_px": [120, 340, 260, 510],
                    "ground_point_m": [14.2, 6.8],
                    "velocity_mps": [1.2, 0.0],
                    "speed_mps": 1.2,
                    "state": {"cov_trace": 0.03, "age_frames": 512, "hits": 498},
                    "zone_ids": ["dock_north"],
                    "ppe": {"helmet": None, "vest": None},
                }
            ],
        }
    )


def sample_trigger_event() -> TriggerEvent:
    return TriggerEvent.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": "evt_01J9ZKTEST",
            "trigger_ts": 1789502412.4,
            "camera_id": "dock_north_01",
            "rule_id": "proximity_forklift_pedestrian",
            "severity_hint": "high",
            "metrics": {"min_distance_m": 1.7, "duration_s": 4.2, "closing_speed_mps": 0.8},
            "involved_track_ids": [42, 77],
            "track_window_ref": "incidents/evt_01J9ZKTEST/tracks.jsonl",
            "clip_ref": "incidents/evt_01J9ZKTEST/clip.mp4",
            "cooldown_key": "dock_north_01:proximity:42+77",
            "calibration_quality": {"rms_px": 1.4, "valid": True},
        }
    )


def test_tracklet_frame_round_trip() -> None:
    frame = sample_tracklet_frame()
    assert TrackletFrame.model_validate_json(frame.model_dump_json()) == frame


def test_trigger_event_round_trip() -> None:
    event = sample_trigger_event()
    assert TriggerEvent.model_validate_json(event.model_dump_json()) == event


def test_calibration_gate_hard_threshold() -> None:
    assert CalibrationQuality.from_rms(RMS_GATE_PX).valid
    assert not CalibrationQuality.from_rms(RMS_GATE_PX + 0.01).valid


def test_incident_record_round_trip() -> None:
    record = IncidentRecord(
        event_id="evt_01J9ZKTEST",
        camera_id="dock_north_01",
        trigger_ts=1789502412.4,
        severity=Severity.HIGH,
        classification=Classification.NEAR_MISS,
        verified_kinematics=KinematicsVerdict(
            verified_min_distance_m=1.72,
            closing_velocity_mps=0.81,
            ttc_s=2.1,
            classification=Classification.NEAR_MISS,
        ),
        narrative_md="Worker inside exclusion envelope.",
        rule_citations=["proximity_forklift_pedestrian"],
    )
    assert IncidentRecord.model_validate_json(record.model_dump_json()) == record
