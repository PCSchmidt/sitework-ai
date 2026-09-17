from __future__ import annotations

from pathlib import Path

from agent.band3 import check
from pipelines.schemas import (
    CalibrationQuality,
    Classification,
    KinematicsVerdict,
    Track,
    TrackletFrame,
    TrackState,
    TriggerEvent,
    TriggerMetrics,
)

_STATE = TrackState(cov_trace=0.01, age_frames=10, hits=10)
_CAL = CalibrationQuality(rms_px=1.0, valid=True)


def _track(track_id: int, x: float, y: float) -> Track:
    return Track(
        track_id=track_id,
        cls="person" if track_id == 42 else "forklift",
        confidence=0.9,
        bbox_px=(0, 0, 10, 10),
        ground_point_m=(x, y),
        state=_STATE,
    )


def _frames() -> list[TrackletFrame]:
    # person (42) closes on the stationary forklift (77) to 1.2m at ts=1000,
    # then separates -- the exact distance sequence (5.0, 3.0, 1.2, 1.6) and
    # ground truth (min 1.2m, closing velocity 1.8 m/s) from spike-01's
    # golden incident (docs/spikes/spike-01-workspace/incidents/evt_test001).
    person_x = [5.0, 3.0, 1.2, 1.6]
    ts = [998.0, 999.0, 1000.0, 1001.0]
    return [
        TrackletFrame(
            camera_id="dock_north_01",
            frame_ts=t,
            seq=i,
            calibration_quality=_CAL,
            tracks=[_track(42, person_x[i], 0.0), _track(77, 0.0, 0.0)],
        )
        for i, t in enumerate(ts)
    ]


def _write_tracks(path: Path, frames: list[TrackletFrame]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for f in frames:
            fh.write(f.model_dump_json() + "\n")


def _event(
    min_distance_m: float | None = 1.2, closing_speed_mps: float | None = None
) -> TriggerEvent:
    return TriggerEvent(
        event_id="evt_test",
        trigger_ts=1000.0,
        camera_id="dock_north_01",
        rule_id="proximity_forklift_pedestrian",
        severity_hint="high",
        metrics=TriggerMetrics(min_distance_m=min_distance_m, closing_speed_mps=closing_speed_mps),
        involved_track_ids=[42, 77],
        track_window_ref="incidents/evt_test/tracks.jsonl",
        cooldown_key="dock_north_01:proximity:42+77",
        calibration_quality=_CAL,
    )


def test_recompute_matches_hand_computed_ground_truth(tmp_path: Path) -> None:
    from agent.band3 import recompute_kinematics

    distance, velocity = recompute_kinematics(_frames(), (42, 77))
    assert distance is not None
    assert abs(distance - 1.2) < 1e-9
    assert velocity is not None
    assert velocity > 0  # closing right before the minimum


def test_gate_passes_when_claims_match_recompute(tmp_path: Path) -> None:
    tracks_path = tmp_path / "tracks.jsonl"
    _write_tracks(tracks_path, _frames())
    verdict = KinematicsVerdict(
        verified_min_distance_m=1.2,
        closing_velocity_mps=1.8,
        classification=Classification.NEAR_MISS,
    )
    result = check(_event(min_distance_m=1.2), verdict, tracks_path)
    assert result.passed
    assert result.reasons == []


def test_gate_rejects_fast_path_distance_mismatch(tmp_path: Path) -> None:
    tracks_path = tmp_path / "tracks.jsonl"
    _write_tracks(tracks_path, _frames())
    verdict = KinematicsVerdict(
        verified_min_distance_m=1.2, classification=Classification.NEAR_MISS
    )
    result = check(_event(min_distance_m=1.7), verdict, tracks_path)  # fast path over-claimed
    assert not result.passed
    assert any("TriggerEvent.metrics.min_distance_m" in r for r in result.reasons)


def test_gate_rejects_agent_kinematics_mismatch(tmp_path: Path) -> None:
    tracks_path = tmp_path / "tracks.jsonl"
    _write_tracks(tracks_path, _frames())
    verdict = KinematicsVerdict(
        verified_min_distance_m=1.2,
        closing_velocity_mps=99.0,
        classification=Classification.NEAR_MISS,
    )
    result = check(_event(min_distance_m=1.2), verdict, tracks_path)
    assert not result.passed
    assert any("closing_velocity_mps" in r for r in result.reasons)


def test_gate_within_tolerance_passes(tmp_path: Path) -> None:
    tracks_path = tmp_path / "tracks.jsonl"
    _write_tracks(tracks_path, _frames())
    # 0.1m off is inside the 0.15m absolute tolerance
    verdict = KinematicsVerdict(
        verified_min_distance_m=1.3, classification=Classification.NEAR_MISS
    )
    result = check(_event(min_distance_m=1.2), verdict, tracks_path)
    assert result.passed


def test_gate_skips_non_pairwise_triggers(tmp_path: Path) -> None:
    tracks_path = tmp_path / "tracks.jsonl"
    _write_tracks(tracks_path, _frames())
    event = _event()
    event = event.model_copy(update={"involved_track_ids": [42]})
    verdict = KinematicsVerdict(classification=Classification.VIOLATION)
    result = check(event, verdict, tracks_path)
    assert result.passed
    assert result.recomputed_min_distance_m is None
