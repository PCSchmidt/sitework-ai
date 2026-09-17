"""Fast-path deterministic rule engine (docs/04 §4, docs/06 §2).

Consumes `TrackletFrame`s in order (per camera) and emits `TriggerEvent`s
when a configured rule condition holds continuously for its threshold,
with cooldown-based dedup on `(camera_id, rule_kind, sorted track_ids)`.
Deterministic, auditable, zero LLM cost -- this is the hard safety-interlock
layer (ADR-001); anything requiring judgment goes through the slow path via
the emitted TriggerEvent, never here.

Scope (M2, per docs/12-roadmap.md): zone_intrusion, proximity, speed.
`ppe_absence` needs a PPE-classifying detector (not built yet) and
`wrong_way` needs lane-direction config that doesn't exist yet -- both are
left for a later milestone; rules of those kinds are loaded but ignored.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from pipelines.config.loader import Rule, RuleKind, RulesConfig
from pipelines.schemas import Severity, TrackletFrame, TriggerEvent, TriggerMetrics

PERSON_CLASS = "person"
VEHICLE_CLASSES = {"vehicle", "heavy_vehicle", "forklift"}

# Rules declare kind/thresholds, not severity (docs/06 §7); this is the
# engine's default mapping until/unless rules.yaml grows a `severity` field.
DEFAULT_SEVERITY: dict[RuleKind, Severity] = {
    RuleKind.ZONE_INTRUSION: Severity.HIGH,
    RuleKind.PROXIMITY: Severity.HIGH,
    RuleKind.SPEED: Severity.MEDIUM,
}

_SUPPORTED_KINDS = frozenset(DEFAULT_SEVERITY)


def _new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex}"


def _in_rule_zone(zone_ids: list[str], rule: Rule) -> bool:
    """A rule with no zone_ids applies everywhere; otherwise requires overlap."""
    return not rule.zone_ids or any(z in rule.zone_ids for z in zone_ids)


@dataclass
class _DwellState:
    entered_ts: float


@dataclass
class _ProximityState:
    started_ts: float
    last_ts: float
    last_distance_m: float
    min_distance_m: float


class RuleEngine:
    """Stateful evaluator: call `process(frame)` once per published TrackletFrame, in ts order."""

    def __init__(self, rules_config: RulesConfig) -> None:
        self._rules = [r for r in rules_config.rules if r.kind in _SUPPORTED_KINDS]
        self._dwell: dict[tuple[str, int, str], _DwellState] = {}  # (camera, track_id, rule_id)
        self._proximity: dict[tuple[str, str, int], _ProximityState] = {}  # (camera, rule_id, pair)
        self._cooldowns: dict[str, float] = {}

    def process(self, frame: TrackletFrame) -> list[TriggerEvent]:
        events: list[TriggerEvent] = []
        for rule in self._rules:
            if rule.kind == RuleKind.ZONE_INTRUSION:
                events.extend(self._eval_zone_intrusion(frame, rule))
            elif rule.kind == RuleKind.PROXIMITY:
                events.extend(self._eval_proximity(frame, rule))
            elif rule.kind == RuleKind.SPEED:
                events.extend(self._eval_speed(frame, rule))
        return events

    # -- shared cooldown/event helpers -----------------------------------

    def _cooldown_key(self, camera_id: str, rule: Rule, track_ids: list[int]) -> str:
        ids = "+".join(str(t) for t in sorted(track_ids))
        return f"{camera_id}:{rule.kind}:{ids}"

    def _ready(self, cooldown_key: str, now: float, cooldown_s: float) -> bool:
        last = self._cooldowns.get(cooldown_key)
        return last is None or (now - last) >= cooldown_s

    def _make_event(
        self,
        frame: TrackletFrame,
        rule: Rule,
        track_ids: list[int],
        metrics: TriggerMetrics,
    ) -> TriggerEvent:
        event_id = _new_event_id()
        return TriggerEvent(
            event_id=event_id,
            trigger_ts=frame.frame_ts,
            camera_id=frame.camera_id,
            rule_id=rule.id,
            severity_hint=DEFAULT_SEVERITY[rule.kind],
            metrics=metrics,
            involved_track_ids=track_ids,
            # Paths pipelines.vision.evidence.EvidenceCapture writes to, once the
            # asynchronous pre/post-trigger window closes (it isn't ready yet at
            # emission time -- the post-trigger half hasn't happened).
            track_window_ref=f"incidents/{event_id}/tracks.jsonl",
            clip_ref=f"incidents/{event_id}/clip.mp4",
            cooldown_key=self._cooldown_key(frame.camera_id, rule, track_ids),
            calibration_quality=frame.calibration_quality,
        )

    def _emit_if_ready(
        self,
        frame: TrackletFrame,
        rule: Rule,
        track_ids: list[int],
        metrics: TriggerMetrics,
    ) -> TriggerEvent | None:
        cooldown_key = self._cooldown_key(frame.camera_id, rule, track_ids)
        if not self._ready(cooldown_key, frame.frame_ts, rule.cooldown_s):
            return None
        self._cooldowns[cooldown_key] = frame.frame_ts
        return self._make_event(frame, rule, track_ids, metrics)

    # -- zone_intrusion: track ground point in zone for >= dwell_s ---------

    def _eval_zone_intrusion(self, frame: TrackletFrame, rule: Rule) -> list[TriggerEvent]:
        assert rule.dwell_s is not None
        events: list[TriggerEvent] = []
        current_keys: set[tuple[str, int, str]] = set()

        for track in frame.tracks:
            if not _in_rule_zone(track.zone_ids, rule):
                continue
            key = (frame.camera_id, track.track_id, rule.id)
            current_keys.add(key)
            state = self._dwell.get(key)
            if state is None:
                self._dwell[key] = _DwellState(entered_ts=frame.frame_ts)
                continue
            dwell_s = frame.frame_ts - state.entered_ts
            if dwell_s >= rule.dwell_s:
                event = self._emit_if_ready(
                    frame, rule, [track.track_id], TriggerMetrics(duration_s=round(dwell_s, 2))
                )
                if event is not None:
                    events.append(event)

        stale = [
            k
            for k in self._dwell
            if k[0] == frame.camera_id and k[2] == rule.id and k not in current_keys
        ]
        for k in stale:
            del self._dwell[k]
        return events

    # -- proximity: min distance(person, vehicle) < radius_m for >= duration_s --

    def _eval_proximity(self, frame: TrackletFrame, rule: Rule) -> list[TriggerEvent]:
        assert rule.radius_m is not None and rule.duration_s is not None
        events: list[TriggerEvent] = []

        persons = [
            t
            for t in frame.tracks
            if t.cls == PERSON_CLASS
            and t.ground_point_m is not None
            and _in_rule_zone(t.zone_ids, rule)
        ]
        vehicles = [
            t
            for t in frame.tracks
            if t.cls in VEHICLE_CLASSES
            and t.ground_point_m is not None
            and _in_rule_zone(t.zone_ids, rule)
        ]

        current_pairs: set[tuple[str, str, int]] = set()
        for person in persons:
            for vehicle in vehicles:
                assert person.ground_point_m is not None and vehicle.ground_point_m is not None
                dx = person.ground_point_m[0] - vehicle.ground_point_m[0]
                dy = person.ground_point_m[1] - vehicle.ground_point_m[1]
                distance_m = (dx * dx + dy * dy) ** 0.5
                if distance_m >= rule.radius_m:
                    continue

                pair_ids = tuple(sorted((person.track_id, vehicle.track_id)))
                pair_key = (frame.camera_id, rule.id, hash(pair_ids))
                current_pairs.add(pair_key)
                state = self._proximity.get(pair_key)
                if state is None:
                    self._proximity[pair_key] = _ProximityState(
                        started_ts=frame.frame_ts,
                        last_ts=frame.frame_ts,
                        last_distance_m=distance_m,
                        min_distance_m=distance_m,
                    )
                    continue

                duration_s = frame.frame_ts - state.started_ts
                dt = frame.frame_ts - state.last_ts
                closing_speed_mps = (state.last_distance_m - distance_m) / dt if dt > 0 else None
                min_distance_m = min(state.min_distance_m, distance_m)
                state.last_ts = frame.frame_ts
                state.last_distance_m = distance_m
                state.min_distance_m = min_distance_m

                if duration_s >= rule.duration_s:
                    event = self._emit_if_ready(
                        frame,
                        rule,
                        [person.track_id, vehicle.track_id],
                        TriggerMetrics(
                            min_distance_m=round(min_distance_m, 3),
                            duration_s=round(duration_s, 2),
                            closing_speed_mps=(
                                round(closing_speed_mps, 3)
                                if closing_speed_mps is not None
                                else None
                            ),
                        ),
                    )
                    if event is not None:
                        events.append(event)

        stale = [
            k
            for k in self._proximity
            if k[0] == frame.camera_id and k[1] == rule.id and k not in current_pairs
        ]
        for k in stale:
            del self._proximity[k]
        return events

    # -- speed: instantaneous ground speed > limit_mps inside a zone --------

    def _eval_speed(self, frame: TrackletFrame, rule: Rule) -> list[TriggerEvent]:
        assert rule.limit_mps is not None
        events: list[TriggerEvent] = []
        for track in frame.tracks:
            if track.speed_mps is None or not _in_rule_zone(track.zone_ids, rule):
                continue
            if track.speed_mps > rule.limit_mps:
                event = self._emit_if_ready(frame, rule, [track.track_id], TriggerMetrics())
                if event is not None:
                    events.append(event)
        return events
