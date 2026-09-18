"""Builds the M3 seeded incident eval set (docs/09 §3, docs/12 M3 exit criterion).

Ten hand-designed incidents (grows to 30+ at M5) covering all three rule kinds
and, deliberately, cases the gate should reject as well as ones it should
confirm -- an eval set that only contains clean passes doesn't test the gate.
Writes `evaluation/fixtures/incidents/{event_id}/{event.json,tracks.jsonl,
expected.json}`. Deterministic and regenerable (docs/09 §5); run again after
editing this file to refresh the fixtures.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pipelines.schemas import (
    CalibrationQuality,
    Severity,
    Track,
    TrackletFrame,
    TrackState,
    TriggerEvent,
    TriggerMetrics,
)

OUT_DIR = Path(__file__).parent / "fixtures" / "incidents"

_CAL = CalibrationQuality(rms_px=1.1, valid=True)
_STATE = TrackState(cov_trace=0.02, age_frames=50, hits=48)


def _track(
    track_id: int, cls: str, x: float, zone_ids: list[str], speed_mps: float | None = None
) -> Track:
    return Track(
        track_id=track_id,
        cls=cls,
        confidence=0.88,
        bbox_px=(0.0, 0.0, 10.0, 10.0),
        ground_point_m=(x, 0.0),
        speed_mps=speed_mps,
        state=_STATE,
        zone_ids=zone_ids,
    )


def _proximity_frames(
    camera_id: str, person_x: list[float], forklift_x: list[float], start_ts: float
) -> list[TrackletFrame]:
    return [
        TrackletFrame(
            camera_id=camera_id,
            frame_ts=start_ts + i,
            seq=i,
            calibration_quality=_CAL,
            tracks=[
                _track(42, "person", person_x[i], []),
                _track(77, "forklift", forklift_x[i], []),
            ],
        )
        for i in range(len(person_x))
    ]


def _multi_track_frames(
    camera_id: str, start_ts: float, tracks_per_frame: list[list[Track]]
) -> list[TrackletFrame]:
    """Like `_proximity_frames` but for fixtures needing >2 simultaneous
    tracks (extra vehicles/people the involved pair has to be picked out
    from) -- `trajectory_inspector.md` filters by the involved track_ids
    from event.json, so extra tracks in the same frame exercise that
    filtering rather than confusing it."""
    return [
        TrackletFrame(
            camera_id=camera_id,
            frame_ts=start_ts + i,
            seq=i,
            calibration_quality=_CAL,
            tracks=tracks,
        )
        for i, tracks in enumerate(tracks_per_frame)
    ]


def _single_track_frames(
    camera_id: str, track_id: int, cls: str, zone_ids_per_frame: list[list[str]], start_ts: float,
    speed_mps_per_frame: list[float | None] | None = None,
) -> list[TrackletFrame]:
    speeds = speed_mps_per_frame or [None] * len(zone_ids_per_frame)
    return [
        TrackletFrame(
            camera_id=camera_id,
            frame_ts=start_ts + i,
            seq=i,
            calibration_quality=_CAL,
            tracks=[_track(track_id, cls, 0.0, zone_ids_per_frame[i], speeds[i])],
        )
        for i in range(len(zone_ids_per_frame))
    ]


def _write(event: TriggerEvent, frames: list[TrackletFrame], expected: dict[str, object]) -> None:
    event_dir = OUT_DIR / event.event_id
    event_dir.mkdir(parents=True, exist_ok=True)
    (event_dir / "event.json").write_text(event.model_dump_json(indent=2), encoding="utf-8")
    with (event_dir / "tracks.jsonl").open("w", encoding="utf-8") as fh:
        for frame in frames:
            fh.write(frame.model_dump_json() + "\n")
    expected_text = json.dumps(expected, indent=2) + "\n"
    (event_dir / "expected.json").write_text(expected_text, encoding="utf-8")


def _proximity_event(
    event_id: str,
    min_distance_m: float,
    duration_s: float,
    closing_speed_mps: float | None,
    involved_track_ids: list[int] | None = None,
) -> TriggerEvent:
    return TriggerEvent(
        event_id=event_id,
        trigger_ts=1000.0 + duration_s,
        camera_id="dock_north_01",
        rule_id="proximity_forklift_pedestrian",
        severity_hint=Severity.HIGH,
        metrics=TriggerMetrics(
            min_distance_m=min_distance_m,
            duration_s=duration_s,
            closing_speed_mps=closing_speed_mps,
        ),
        involved_track_ids=involved_track_ids or [42, 77],
        track_window_ref=f"incidents/{event_id}/tracks.jsonl",
        cooldown_key=f"dock_north_01:proximity:{event_id}",
        calibration_quality=_CAL,
    )


def _zone_event(event_id: str, duration_s: float, track_id: int = 88) -> TriggerEvent:
    return TriggerEvent(
        event_id=event_id,
        trigger_ts=1000.0 + duration_s,
        camera_id="yard_excavator_01",
        rule_id="intrusion_excavator_swing",
        severity_hint=Severity.HIGH,
        metrics=TriggerMetrics(duration_s=duration_s),
        involved_track_ids=[track_id],
        track_window_ref=f"incidents/{event_id}/tracks.jsonl",
        cooldown_key=f"yard_excavator_01:zone_intrusion:{event_id}",
        calibration_quality=_CAL,
    )


def _speed_event(event_id: str, track_id: int = 99) -> TriggerEvent:
    return TriggerEvent(
        event_id=event_id,
        trigger_ts=1003.0,
        camera_id="dock_north_01",
        rule_id="speed_limit_dock",
        severity_hint=Severity.MEDIUM,
        metrics=TriggerMetrics(),
        involved_track_ids=[track_id],
        track_window_ref=f"incidents/{event_id}/tracks.jsonl",
        cooldown_key=f"dock_north_01:speed:{event_id}",
        calibration_quality=_CAL,
    )


def build() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)

    # 1. proximity / near_miss -- clean, everything self-consistent.
    eid = "evt_seed_near_miss_01"
    frames = _proximity_frames("dock_north_01", [4.0, 2.5, 1.4, 1.9], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=1.4, duration_s=3.0, closing_speed_mps=1.1)
    _write(
        event,
        frames,
        {
            "expected_state": "confirmed",
            "expected_classification": "near_miss",
            "check_classification": True,
            "notes": "clean near-miss; fast path claim matches recompute",
        },
    )

    # 2. proximity / violation.
    eid = "evt_seed_violation_01"
    frames = _proximity_frames("dock_north_01", [3.0, 1.6, 0.7, 1.0], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=0.7, duration_s=3.0, closing_speed_mps=0.9)
    _write(
        event,
        frames,
        {
            "expected_state": "confirmed",
            "expected_classification": "violation",
            "check_classification": True,
            "notes": "clean violation, well inside the 1.0m threshold",
        },
    )

    # 3. proximity / normal_ops -- triggered (< radius_m) but never gets close.
    eid = "evt_seed_normal_ops_01"
    frames = _proximity_frames("dock_north_01", [3.0, 2.8, 2.6, 2.7], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=2.6, duration_s=3.0, closing_speed_mps=0.2)
    _write(
        event,
        frames,
        {
            "expected_state": "confirmed",
            "expected_classification": "normal_ops",
            "check_classification": True,
            "notes": "inside proximity radius_m but never near_miss-close",
        },
    )

    # 4. proximity / near_miss -- minimal 2-frame evidence window (edge case).
    eid = "evt_seed_minimal_window_01"
    frames = _proximity_frames("dock_north_01", [3.0, 1.8], [0.0] * 2, 1000.0)
    event = _proximity_event(eid, min_distance_m=1.8, duration_s=1.0, closing_speed_mps=1.2)
    _write(
        event,
        frames,
        {
            "expected_state": "confirmed",
            "expected_classification": "near_miss",
            "check_classification": True,
            "notes": "only 2 frames in the window -- exercises the minimal-data path",
        },
    )

    # 5. proximity / evidence-capture inconsistency -- TriggerEvent's own claim
    # doesn't match tracks.jsonl (simulated capture-window bug). Band-3 must
    # reject this regardless of what the agent says; not a test of the LLM.
    eid = "evt_seed_evidence_inconsistent_01"
    frames = _proximity_frames("dock_north_01", [3.5, 3.0, 2.6, 2.9], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=1.0, duration_s=3.0, closing_speed_mps=0.5)
    _write(
        event,
        frames,
        {
            "expected_state": "needs_review",
            "expected_classification": None,
            "check_classification": False,
            "notes": (
                "TriggerEvent claims min_distance_m=1.0 but tracks.jsonl's real minimum is "
                "2.6m -- simulated evidence-capture bug; Band-3 must reject on the fast-path "
                "side of the cross-check even if the agent's own recompute is correct"
            ),
        },
    )

    # 6. proximity / near_miss with a live TTC (still closing at the last frame).
    eid = "evt_seed_ttc_closing_01"
    frames = _proximity_frames("dock_north_01", [5.0, 3.5, 2.2, 1.3], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=1.3, duration_s=3.0, closing_speed_mps=0.9)
    _write(
        event,
        frames,
        {
            "expected_state": "confirmed",
            "expected_classification": "near_miss",
            "check_classification": True,
            "notes": "still closing at the last frame -- ttc_s should be non-null",
        },
    )

    # 7. zone_intrusion / violation -- dwells in the swing radius the whole window.
    eid = "evt_seed_zone_violation_01"
    frames = _single_track_frames(
        "yard_excavator_01", 88, "person", [["excavator_swing_radius"]] * 5, 1000.0
    )
    event = _zone_event(eid, duration_s=4.0)
    _write(
        event,
        frames,
        {
            "expected_state": "confirmed",
            "expected_classification": "violation",
            "check_classification": True,
            "notes": "track in the exclusion zone for the whole captured window",
        },
    )

    # 8. zone_intrusion / false_positive -- claimed dwell doesn't hold up: the
    # track is only actually in the zone for 1 of 5 frames.
    eid = "evt_seed_zone_false_positive_01"
    frames = _single_track_frames(
        "yard_excavator_01",
        88,
        "person",
        [[], [], ["excavator_swing_radius"], [], []],
        1000.0,
    )
    event = _zone_event(eid, duration_s=3.5)
    _write(
        event,
        frames,
        {
            "expected_state": "confirmed",
            "expected_classification": "false_positive",
            "check_classification": True,
            "notes": "dwell claim doesn't hold up against tracks.jsonl (1 of 5 frames in zone)",
        },
    )

    # 9. speed / violation -- consistently over the limit.
    eid = "evt_seed_speed_violation_01"
    frames = _single_track_frames(
        "dock_north_01",
        99,
        "forklift",
        [["dock_north"]] * 4,
        1000.0,
        speed_mps_per_frame=[3.4, 3.6, 3.5, 3.3],
    )
    event = _speed_event(eid)
    _write(
        event,
        frames,
        {
            "expected_state": "confirmed",
            "expected_classification": "violation",
            "check_classification": True,
            "notes": "speed_mps consistently well above the 2.2 m/s dock limit",
        },
    )

    # 10. speed / false_positive -- claimed speed violation, but tracks show
    # the vehicle under the limit the whole captured window.
    eid = "evt_seed_speed_false_positive_01"
    frames = _single_track_frames(
        "dock_north_01",
        99,
        "forklift",
        [["dock_north"]] * 4,
        1000.0,
        speed_mps_per_frame=[1.6, 1.8, 1.7, 1.9],
    )
    event = _speed_event(eid)
    _write(
        event,
        frames,
        {
            "expected_state": "confirmed",
            "expected_classification": "false_positive",
            "check_classification": True,
            "notes": "speed_mps stays under the 2.2 m/s limit for the whole captured window",
        },
    )

    # -- M5: expanded from 10 to 30+ (docs/12 M5 item 2) -----------------
    # The 20 fixtures below target the boundaries `trajectory_inspector.md`
    # §6 actually uses (near_miss <2.0m, violation <1.0m), multi-track
    # scenes (does the agent pick the right pair out of several tracks?),
    # and more false_positive/needs_review variety for zone/speed -- the
    # first 10 leaned proximity-heavy and only had one gate-rejection case.

    # 11. proximity / near_miss -- just inside the 2.0m near_miss boundary.
    eid = "evt_seed_near_miss_boundary_close_01"
    frames = _proximity_frames("dock_north_01", [5.0, 3.5, 2.2, 1.95], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=1.95, duration_s=3.0, closing_speed_mps=0.6)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "near_miss",
            "check_classification": True,
            "notes": "min_distance 1.95m -- just inside the <2.0m near_miss boundary",
        },
    )

    # 12. proximity / normal_ops -- just outside the 2.0m boundary.
    eid = "evt_seed_normal_ops_boundary_01"
    frames = _proximity_frames("dock_north_01", [5.0, 4.0, 3.0, 2.05], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=2.05, duration_s=3.0, closing_speed_mps=0.4)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "normal_ops",
            "check_classification": True,
            "notes": "min_distance 2.05m -- just outside the near_miss boundary",
        },
    )

    # 13. proximity / violation -- just inside the 1.0m violation boundary.
    eid = "evt_seed_violation_boundary_01"
    frames = _proximity_frames("dock_north_01", [3.0, 2.0, 1.2, 0.95], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=0.95, duration_s=3.0, closing_speed_mps=0.9)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "violation",
            "check_classification": True,
            "notes": "min_distance 0.95m -- just inside the <1.0m violation boundary",
        },
    )

    # 14. proximity / near_miss -- just outside the 1.0m boundary (still near_miss, not violation).
    eid = "evt_seed_near_miss_boundary_far_01"
    frames = _proximity_frames("dock_north_01", [3.0, 2.0, 1.3, 1.05], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=1.05, duration_s=3.0, closing_speed_mps=0.8)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "near_miss",
            "check_classification": True,
            "notes": "min_distance 1.05m -- inside near_miss range, just outside violation",
        },
    )

    # 15. proximity / violation -- severe, near-contact.
    eid = "evt_seed_violation_severe_01"
    frames = _proximity_frames("dock_north_01", [3.0, 1.5, 0.5, 0.2], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=0.2, duration_s=3.0, closing_speed_mps=1.4)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "violation",
            "check_classification": True,
            "notes": "min_distance 0.2m -- near-contact severe violation",
        },
    )

    # 16. proximity / near_miss -- longer 8-frame window, plateaus near the boundary.
    eid = "evt_seed_near_miss_long_dwell_01"
    frames = _proximity_frames(
        "dock_north_01", [5.0, 4.0, 3.0, 2.2, 1.8, 1.6, 1.5, 1.5], [0.0] * 8, 1000.0
    )
    event = _proximity_event(eid, min_distance_m=1.5, duration_s=7.0, closing_speed_mps=0.3)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "near_miss",
            "check_classification": True,
            "notes": "8-frame window, distance plateaus at 1.5m near_miss rather than a single dip",
        },
    )

    # 17. proximity / evidence-capture inconsistency, more severe than fixture 5 --
    # TriggerEvent claims a violation-level distance the real tracks never support.
    eid = "evt_seed_evidence_inconsistent_02"
    frames = _proximity_frames("dock_north_01", [4.0, 3.5, 3.0, 2.7], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=0.5, duration_s=3.0, closing_speed_mps=1.0)
    _write(
        event, frames,
        {
            "expected_state": "needs_review", "expected_classification": None,
            "check_classification": False,
            "notes": (
                "TriggerEvent claims min_distance_m=0.5 (violation) but tracks.jsonl's real "
                "minimum is 2.7m (normal_ops) -- a larger fast-path/evidence gap than fixture 5"
            ),
        },
    )

    # 18. zone_intrusion / violation -- longer 7-frame full dwell, different track.
    eid = "evt_seed_zone_violation_long_01"
    frames = _single_track_frames(
        "yard_excavator_01", 90, "person", [["excavator_swing_radius"]] * 7, 1000.0
    )
    event = _zone_event(eid, duration_s=6.0, track_id=90)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "violation",
            "check_classification": True,
            "notes": "7-frame window, track dwells in the swing radius the entire time",
        },
    )

    # 19. zone_intrusion / violation -- dwell just over the 3.0s config threshold.
    eid = "evt_seed_zone_violation_edge_01"
    frames = _single_track_frames(
        "yard_excavator_01", 91, "person", [["excavator_swing_radius"]] * 5, 1000.0
    )
    event = _zone_event(eid, duration_s=3.1, track_id=91)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "violation",
            "check_classification": True,
            "notes": "dwell 3.1s -- just over the dwell_s=3.0 threshold, full-window presence",
        },
    )

    # 20. zone_intrusion / false_positive -- track leaves and re-enters; claimed
    # continuous dwell doesn't hold up against the broken presence.
    eid = "evt_seed_zone_false_positive_reentry_01"
    frames = _single_track_frames(
        "yard_excavator_01",
        92,
        "person",
        [["excavator_swing_radius"], [], [], ["excavator_swing_radius"], []],
        1000.0,
    )
    event = _zone_event(eid, duration_s=4.0, track_id=92)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "false_positive",
            "check_classification": True,
            "notes": "track exits and re-enters the zone -- claimed continuous dwell is false",
        },
    )

    # 21. speed / violation -- just over the 2.2 m/s limit.
    eid = "evt_seed_speed_violation_edge_01"
    frames = _single_track_frames(
        "dock_north_01", 93, "forklift", [["dock_north"]] * 4, 1000.0,
        speed_mps_per_frame=[2.3, 2.4, 2.3, 2.35],
    )
    event = _speed_event(eid, track_id=93)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "violation",
            "check_classification": True,
            "notes": "speed_mps just over the 2.2 m/s limit every frame",
        },
    )

    # 22. speed / false_positive -- fluctuates near the limit but never actually exceeds it.
    eid = "evt_seed_speed_false_positive_fluctuating_01"
    frames = _single_track_frames(
        "dock_north_01", 94, "forklift", [["dock_north"]] * 4, 1000.0,
        speed_mps_per_frame=[2.1, 1.9, 2.15, 1.8],
    )
    event = _speed_event(eid, track_id=94)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "false_positive",
            "check_classification": True,
            "notes": "speed_mps hovers near 2.2 m/s but never actually crosses it",
        },
    )

    # 23. speed / violation -- severe, well over the limit.
    eid = "evt_seed_speed_violation_severe_01"
    frames = _single_track_frames(
        "dock_north_01", 95, "forklift", [["dock_north"]] * 4, 1000.0,
        speed_mps_per_frame=[5.0, 5.2, 5.1, 4.9],
    )
    event = _speed_event(eid, track_id=95)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "violation",
            "check_classification": True,
            "notes": "speed_mps more than double the 2.2 m/s limit",
        },
    )

    # 24. proximity / near_miss -- a third track (a second, distant forklift) present
    # in every frame; the agent has to pick the involved pair out, not just the closest ever seen.
    eid = "evt_seed_proximity_multi_vehicle_01"
    frames = _multi_track_frames(
        "dock_north_01", 1000.0,
        [
            [
                _track(42, "person", px, []),
                _track(77, "forklift", 0.0, []),
                _track(78, "forklift", 10.0, []),
            ]
            for px in [4.0, 3.0, 2.0, 1.5]
        ],
    )
    event = _proximity_event(
        eid, min_distance_m=1.5, duration_s=3.0, closing_speed_mps=0.7,
        involved_track_ids=[42, 77],
    )
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "near_miss",
            "check_classification": True,
            "notes": "a second, distant (10m) forklift is present in every frame as a distractor",
        },
    )

    # 25. proximity / violation -- a second, distant person present as a distractor.
    eid = "evt_seed_proximity_multi_person_01"
    frames = _multi_track_frames(
        "dock_north_01", 1000.0,
        [
            [
                _track(42, "person", px, []),
                _track(43, "person", 10.0, []),
                _track(77, "forklift", 0.0, []),
            ]
            for px in [3.0, 2.0, 1.0, 0.8]
        ],
    )
    event = _proximity_event(
        eid, min_distance_m=0.8, duration_s=3.0, closing_speed_mps=1.1,
        involved_track_ids=[42, 77],
    )
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "violation",
            "check_classification": True,
            "notes": "a second, distant (10m) person is present in every frame as a distractor",
        },
    )

    # 26. proximity / near_miss -- stationary forklift, pedestrian walks in.
    eid = "evt_seed_near_miss_approaching_stationary_01"
    frames = _proximity_frames("dock_north_01", [4.0, 3.2, 2.4, 1.7], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=1.7, duration_s=3.0, closing_speed_mps=0.5)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "near_miss",
            "check_classification": True,
            "notes": "forklift stationary the whole window; pedestrian is the only one moving",
        },
    )

    # 27. proximity / normal_ops -- the pair is moving apart the entire window.
    eid = "evt_seed_normal_ops_moving_apart_01"
    frames = _proximity_frames("dock_north_01", [2.4, 2.6, 2.8, 3.0], [0.0] * 4, 1000.0)
    event = _proximity_event(eid, min_distance_m=2.4, duration_s=3.0, closing_speed_mps=-0.2)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "normal_ops",
            "check_classification": True,
            "notes": "distance only increases across the window -- separating, not closing",
        },
    )

    # 28. zone_intrusion / false_positive -- track is in the zone for only the first
    # of 5 frames, then leaves for good; claimed dwell doesn't hold up.
    eid = "evt_seed_zone_false_positive_brief_01"
    frames = _single_track_frames(
        "yard_excavator_01", 97, "person", [["excavator_swing_radius"], [], [], [], []], 1000.0
    )
    event = _zone_event(eid, duration_s=4.0, track_id=97)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "false_positive",
            "check_classification": True,
            "notes": "track is in the zone for only the first captured frame, then leaves for good",
        },
    )

    # 29. speed / violation -- accelerating through the window, over the limit by the end.
    eid = "evt_seed_speed_violation_accelerating_01"
    frames = _single_track_frames(
        "dock_north_01", 98, "forklift", [["dock_north"]] * 4, 1000.0,
        speed_mps_per_frame=[1.8, 2.0, 2.4, 2.6],
    )
    event = _speed_event(eid, track_id=98)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "violation",
            "check_classification": True,
            "notes": "ramps from under to well over the 2.2 m/s limit across the window",
        },
    )

    # 30. proximity / violation -- minimal 2-frame window at violation-level distance.
    eid = "evt_seed_proximity_minimal_violation_01"
    frames = _proximity_frames("dock_north_01", [2.0, 0.6], [0.0] * 2, 1000.0)
    event = _proximity_event(eid, min_distance_m=0.6, duration_s=1.0, closing_speed_mps=1.4)
    _write(
        event, frames,
        {
            "expected_state": "confirmed", "expected_classification": "violation",
            "check_classification": True,
            "notes": "only 2 frames, but the minimal window is itself at violation-level distance",
        },
    )

    print(f"wrote {len(list(OUT_DIR.iterdir()))} fixtures to {OUT_DIR}")


if __name__ == "__main__":
    build()
