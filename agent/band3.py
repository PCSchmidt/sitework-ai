"""Band-3 recomputation gate (docs/06 §3, normative).

Recomputes min-distance/closing-velocity from the captured `tracks.jsonl`
using the *same* pairwise ground-distance math `RuleEngine._eval_proximity`
uses (pipelines/vision/rules.py) -- no re-tracking, no interpolation, replayed
at the stored sample indices -- then rejects on mismatch against either what
the fast path claimed (`TriggerEvent.metrics`) or what the agent claims
(`KinematicsVerdict`).

Proximity triggers (exactly two `involved_track_ids`) get the pairwise
distance/velocity check. Zone-intrusion triggers (one track) get a verdict
consistency check: the track's continuous in-zone time at the trigger frame
is recomputed from the same `zone_ids` the fast path stored, and the agent's
classification must agree with it -- `violation` needs the dwell limit met,
`false_positive` needs it not met (normal_ops/near_miss are judgment calls
and pass). The fast path's own `duration_s` claim is deliberately *not*
gated here: refuting a wrong fast-path claim is the agent's job, and a
correct refutation must be able to reach `confirmed`. Speed triggers still
pass on schema validation alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipelines.config.loader import RuleKind, RulesConfig
from pipelines.schemas import (
    DISTANCE_TOL_M,
    RELATIVE_TOL,
    VELOCITY_TOL_MPS,
    Classification,
    KinematicsVerdict,
    TrackletFrame,
    TriggerEvent,
)

# docs/06 §3's time tolerance (|Δtime| <= 0.2 s), applied to the zone dwell limit.
TIME_TOL_S = 0.2


@dataclass(frozen=True)
class Band3Result:
    passed: bool
    reasons: list[str]
    recomputed_min_distance_m: float | None
    recomputed_closing_velocity_mps: float | None
    recomputed_dwell_s: float | None = None


def _within_tol(claimed: float, recomputed: float, abs_tol: float) -> bool:
    diff = abs(claimed - recomputed)
    rel = abs(claimed) * RELATIVE_TOL
    return diff <= max(abs_tol, rel)


def load_tracks(tracks_path: Path) -> list[TrackletFrame]:
    frames = []
    with tracks_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                frames.append(TrackletFrame.model_validate_json(line))
    return frames


def recompute_kinematics(
    frames: list[TrackletFrame], track_ids: tuple[int, int]
) -> tuple[float | None, float | None]:
    """Pairwise ground-distance across the stored window; mirrors
    `RuleEngine._eval_proximity`'s per-frame distance math. Closing velocity
    is reported at the minimum-distance frame -- the rate distance decreased
    between the frame before the minimum and the minimum itself (docs/06 §3,
    spike-01's golden-incident definition) -- not the window's last interval,
    which may already be separating again."""
    id_a, id_b = track_ids
    samples: list[tuple[float, float]] = []  # (frame_ts, distance_m)

    for frame in sorted(frames, key=lambda f: f.frame_ts):
        by_id = {t.track_id: t for t in frame.tracks}
        a, b = by_id.get(id_a), by_id.get(id_b)
        if a is None or b is None or a.ground_point_m is None or b.ground_point_m is None:
            continue
        dx = a.ground_point_m[0] - b.ground_point_m[0]
        dy = a.ground_point_m[1] - b.ground_point_m[1]
        distance_m = (dx * dx + dy * dy) ** 0.5
        samples.append((frame.frame_ts, distance_m))

    if not samples:
        return None, None

    min_idx = min(range(len(samples)), key=lambda i: samples[i][1])
    min_ts, min_distance_m = samples[min_idx]

    closing_velocity_mps: float | None = None
    if min_idx > 0:
        prev_ts, prev_distance_m = samples[min_idx - 1]
        dt = min_ts - prev_ts
        if dt > 0:
            closing_velocity_mps = (prev_distance_m - min_distance_m) / dt

    return min_distance_m, closing_velocity_mps


def recompute_zone_dwell(
    frames: list[TrackletFrame], track_id: int, zone_ids: list[str], until_ts: float
) -> float | None:
    """Continuous time the track has been inside any of `zone_ids` as of the last
    frame at or before `until_ts` (the trigger), mirroring RuleEngine's dwell
    (`frame_ts - entered_ts`). None if the track isn't in the zone at that frame."""
    entered: float | None = None
    last_ts: float | None = None
    for frame in sorted(frames, key=lambda f: f.frame_ts):
        if frame.frame_ts > until_ts + 1e-6:
            break
        track = next((t for t in frame.tracks if t.track_id == track_id), None)
        in_zone = track is not None and any(z in zone_ids for z in track.zone_ids)
        if not in_zone:
            entered = None
        elif entered is None:
            entered = frame.frame_ts
        last_ts = frame.frame_ts
    if entered is None or last_ts is None:
        return None
    return last_ts - entered


def _check_zone_intrusion(
    event: TriggerEvent, verdict: KinematicsVerdict, tracks_path: Path, rules: RulesConfig
) -> Band3Result:
    rule = next((r for r in rules.rules if r.id == event.rule_id), None)
    if rule is None or rule.kind != RuleKind.ZONE_INTRUSION or rule.dwell_s is None:
        return Band3Result(True, [], None, None)
    frames = load_tracks(tracks_path)
    dwell = recompute_zone_dwell(
        frames, event.involved_track_ids[0], rule.zone_ids, event.trigger_ts
    )
    supported = dwell is not None and dwell >= rule.dwell_s - TIME_TOL_S
    shown = "not in the zone at the trigger frame" if dwell is None else f"{dwell:.2f}s"
    reasons: list[str] = []
    if verdict.classification == Classification.VIOLATION and not supported:
        reasons.append(
            f"agent classified violation, but recompute shows track {event.involved_track_ids[0]} "
            f"in {rule.zone_ids}: {shown} (dwell limit {rule.dwell_s}s, tol {TIME_TOL_S}s)"
        )
    if verdict.classification == Classification.FALSE_POSITIVE and supported:
        reasons.append(
            f"agent classified false_positive, but recompute shows track "
            f"{event.involved_track_ids[0]} in {rule.zone_ids} for {shown} continuously at the "
            f"trigger, meeting the {rule.dwell_s}s dwell limit (tol {TIME_TOL_S}s)"
        )
    return Band3Result(not reasons, reasons, None, None, recomputed_dwell_s=dwell)


def check(
    event: TriggerEvent,
    verdict: KinematicsVerdict,
    tracks_path: Path,
    rules: RulesConfig | None = None,
) -> Band3Result:
    if len(event.involved_track_ids) == 1 and rules is not None:
        return _check_zone_intrusion(event, verdict, tracks_path, rules)
    if len(event.involved_track_ids) != 2:
        return Band3Result(True, [], None, None)

    track_ids = (event.involved_track_ids[0], event.involved_track_ids[1])
    frames = load_tracks(tracks_path)
    recomputed_distance, recomputed_velocity = recompute_kinematics(frames, track_ids)

    if recomputed_distance is None:
        return Band3Result(
            False,
            ["recompute found no frame with both involved tracks on the ground plane"],
            None,
            None,
        )

    reasons: list[str] = []
    for label, claimed in (
        ("TriggerEvent.metrics.min_distance_m", event.metrics.min_distance_m),
        ("KinematicsVerdict.verified_min_distance_m", verdict.verified_min_distance_m),
    ):
        if claimed is not None and not _within_tol(claimed, recomputed_distance, DISTANCE_TOL_M):
            reasons.append(
                f"{label}={claimed} vs recomputed {recomputed_distance:.3f}m "
                f"(tol {DISTANCE_TOL_M}m / {RELATIVE_TOL:.0%})"
            )

    if (
        recomputed_velocity is not None
        and verdict.closing_velocity_mps is not None
        and not _within_tol(verdict.closing_velocity_mps, recomputed_velocity, VELOCITY_TOL_MPS)
    ):
        reasons.append(
            f"KinematicsVerdict.closing_velocity_mps={verdict.closing_velocity_mps} vs recomputed "
            f"{recomputed_velocity:.3f}m/s (tol {VELOCITY_TOL_MPS}m/s / {RELATIVE_TOL:.0%})"
        )

    return Band3Result(
        passed=not reasons,
        reasons=reasons,
        recomputed_min_distance_m=recomputed_distance,
        recomputed_closing_velocity_mps=recomputed_velocity,
    )
