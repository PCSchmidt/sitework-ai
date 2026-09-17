from __future__ import annotations

from pipelines.config.loader import Rule, RuleKind, RulesConfig
from pipelines.schemas import CalibrationQuality, Track, TrackletFrame, TrackState
from pipelines.vision.rules import RuleEngine

VALID_QUALITY = CalibrationQuality(rms_px=1.0, valid=True)
STATE = TrackState(cov_trace=0.0, age_frames=1, hits=1)


def _frame(camera_id: str, frame_ts: float, seq: int, tracks: list[Track]) -> TrackletFrame:
    return TrackletFrame(
        camera_id=camera_id,
        frame_ts=frame_ts,
        seq=seq,
        calibration_quality=VALID_QUALITY,
        tracks=tracks,
    )


def _track(track_id: int, cls: str, zone_ids: list[str] | None = None, **kwargs: object) -> Track:
    return Track(
        track_id=track_id,
        cls=cls,
        confidence=0.9,
        bbox_px=(0.0, 0.0, 10.0, 10.0),
        state=STATE,
        zone_ids=zone_ids or [],
        **kwargs,  # type: ignore[arg-type]
    )


# ---- zone_intrusion ----------------------------------------------------

INTRUSION_RULE = Rule(
    id="test_intrusion",
    kind=RuleKind.ZONE_INTRUSION,
    description="d",
    zone_ids=["zoneA"],
    dwell_s=3.0,
    cooldown_s=10.0,
)


def test_zone_intrusion_fires_only_after_dwell_threshold() -> None:
    engine = RuleEngine(RulesConfig(rules=[INTRUSION_RULE]))
    fired_at = []
    for ts in range(5):
        events = engine.process(_frame("cam1", float(ts), ts, [_track(1, "person", ["zoneA"])]))
        if events:
            fired_at.append(ts)
    assert fired_at == [3]


def test_zone_intrusion_respects_cooldown() -> None:
    engine = RuleEngine(RulesConfig(rules=[INTRUSION_RULE]))
    fired_at = []
    for ts in range(15):
        events = engine.process(_frame("cam1", float(ts), ts, [_track(1, "person", ["zoneA"])]))
        if events:
            fired_at.append(ts)
    # fires at dwell=3, then cooldown_s=10 blocks until ts=13 (dwell continues accruing from
    # original entry, so it's still >= dwell_s every subsequent frame)
    assert fired_at == [3, 13]


def test_zone_intrusion_resets_when_track_leaves_zone() -> None:
    engine = RuleEngine(RulesConfig(rules=[INTRUSION_RULE]))
    for ts in (0, 1):
        engine.process(_frame("cam1", float(ts), ts, [_track(1, "person", ["zoneA"])]))
    # leaves the zone before the dwell threshold
    engine.process(_frame("cam1", 2.0, 2, [_track(1, "person", [])]))
    # re-enters; dwell timer must restart, not resume from ts=0
    events_at_3 = engine.process(_frame("cam1", 3.0, 3, [_track(1, "person", ["zoneA"])]))
    assert events_at_3 == []
    events_at_6 = engine.process(_frame("cam1", 6.0, 4, [_track(1, "person", ["zoneA"])]))
    assert len(events_at_6) == 1


def test_zone_intrusion_ignores_tracks_outside_rule_zone() -> None:
    engine = RuleEngine(RulesConfig(rules=[INTRUSION_RULE]))
    for ts in range(5):
        events = engine.process(
            _frame("cam1", float(ts), ts, [_track(1, "person", ["other_zone"])])
        )
        assert events == []


# ---- proximity ----------------------------------------------------------

PROXIMITY_RULE = Rule(
    id="test_proximity",
    kind=RuleKind.PROXIMITY,
    description="d",
    radius_m=3.0,
    duration_s=2.0,
    cooldown_s=5.0,
)


def test_proximity_fires_after_duration_with_correct_metrics() -> None:
    engine = RuleEngine(RulesConfig(rules=[PROXIMITY_RULE]))
    person = lambda gp: _track(1, "person", ground_point_m=gp)  # noqa: E731
    vehicle = lambda gp: _track(2, "vehicle", ground_point_m=gp)  # noqa: E731

    e0 = engine.process(_frame("cam1", 0.0, 0, [person((0.0, 0.0)), vehicle((2.0, 0.0))]))
    assert e0 == []
    e1 = engine.process(_frame("cam1", 1.0, 1, [person((0.0, 0.0)), vehicle((1.0, 0.0))]))
    assert e1 == []
    e2 = engine.process(_frame("cam1", 2.0, 2, [person((0.0, 0.0)), vehicle((1.0, 0.0))]))
    assert len(e2) == 1
    event = e2[0]
    assert set(event.involved_track_ids) == {1, 2}
    assert event.metrics.min_distance_m == 1.0
    assert event.metrics.duration_s == 2.0
    # closing_speed_mps reflects the most recent interval (ts=1 -> ts=2: 1.0m -> 1.0m, no change);
    # the earlier 2.0m -> 1.0m close happened between the init frame (ts=0) and ts=1.
    assert event.metrics.closing_speed_mps == 0.0


def test_proximity_resets_when_pair_separates() -> None:
    engine = RuleEngine(RulesConfig(rules=[PROXIMITY_RULE]))
    person = lambda gp: _track(1, "person", ground_point_m=gp)  # noqa: E731
    vehicle = lambda gp: _track(2, "vehicle", ground_point_m=gp)  # noqa: E731

    engine.process(_frame("cam1", 0.0, 0, [person((0.0, 0.0)), vehicle((1.0, 0.0))]))
    # separates beyond radius before duration_s elapses
    engine.process(_frame("cam1", 1.0, 1, [person((0.0, 0.0)), vehicle((10.0, 0.0))]))
    # comes back close; timer must restart
    events = engine.process(_frame("cam1", 2.0, 2, [person((0.0, 0.0)), vehicle((1.0, 0.0))]))
    assert events == []


def test_proximity_ignores_same_class_pairs() -> None:
    engine = RuleEngine(RulesConfig(rules=[PROXIMITY_RULE]))
    for ts in range(4):
        events = engine.process(
            _frame(
                "cam1",
                float(ts),
                ts,
                [
                    _track(1, "person", ground_point_m=(0.0, 0.0)),
                    _track(2, "person", ground_point_m=(0.5, 0.0)),
                ],
            )
        )
        assert events == []


# ---- speed ---------------------------------------------------------------

SPEED_RULE = Rule(
    id="test_speed",
    kind=RuleKind.SPEED,
    description="d",
    zone_ids=["zoneA"],
    limit_mps=2.0,
    cooldown_s=5.0,
)


def test_speed_fires_immediately_over_limit_in_zone() -> None:
    engine = RuleEngine(RulesConfig(rules=[SPEED_RULE]))
    events = engine.process(
        _frame("cam1", 0.0, 0, [_track(1, "forklift", ["zoneA"], speed_mps=3.0)])
    )
    assert len(events) == 1
    assert events[0].involved_track_ids == [1]


def test_speed_does_not_fire_under_limit() -> None:
    engine = RuleEngine(RulesConfig(rules=[SPEED_RULE]))
    events = engine.process(
        _frame("cam1", 0.0, 0, [_track(1, "forklift", ["zoneA"], speed_mps=1.0)])
    )
    assert events == []


def test_speed_does_not_fire_outside_zone() -> None:
    engine = RuleEngine(RulesConfig(rules=[SPEED_RULE]))
    events = engine.process(_frame("cam1", 0.0, 0, [_track(1, "forklift", [], speed_mps=3.0)]))
    assert events == []


def test_speed_respects_cooldown() -> None:
    engine = RuleEngine(RulesConfig(rules=[SPEED_RULE]))
    fired_at = []
    for ts in range(12):
        events = engine.process(
            _frame("cam1", float(ts), ts, [_track(1, "forklift", ["zoneA"], speed_mps=3.0)])
        )
        if events:
            fired_at.append(ts)
    assert fired_at == [0, 5, 10]


# ---- unsupported rule kinds are loaded but silently ignored ---------------


def test_unsupported_rule_kinds_are_ignored_without_error() -> None:
    wrong_way_rule = Rule(id="test_wrong_way", kind=RuleKind.WRONG_WAY, description="d")
    engine = RuleEngine(RulesConfig(rules=[wrong_way_rule]))
    events = engine.process(_frame("cam1", 0.0, 0, [_track(1, "vehicle", ["zoneA"])]))
    assert events == []


# ---- cooldown_key / event shape -------------------------------------------


def test_cooldown_key_matches_docs_convention() -> None:
    engine = RuleEngine(RulesConfig(rules=[PROXIMITY_RULE]))
    person = _track(42, "person", ground_point_m=(0.0, 0.0))
    vehicle = _track(7, "vehicle", ground_point_m=(1.0, 0.0))
    engine.process(_frame("dock_north_01", 0.0, 0, [person, vehicle]))
    engine.process(_frame("dock_north_01", 1.0, 1, [person, vehicle]))
    events = engine.process(_frame("dock_north_01", 2.0, 2, [person, vehicle]))
    assert events[0].cooldown_key == "dock_north_01:proximity:7+42"
    assert events[0].event_id.startswith("evt_")
    assert events[0].track_window_ref == f"incidents/{events[0].event_id}/tracks.jsonl"
