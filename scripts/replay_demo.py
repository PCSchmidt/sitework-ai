"""Simulated-live replay mode (docs/12 M6): fixtures -> cloud backend, $0 public demo.

Replays the M5 seeded-incident fixtures (evaluation/fixtures/incidents/) as a
looping "live" incident feed against the real API/DB/dashboard stack, with no
GPU vision container and no LLM agent call in the loop -- the two components
that cost real money (compute or tokens) to run continuously. This is what
lets a public-facing demo instance run for $0/mo (docs/11-risks.md rollback
position #2) instead of needing the GPU vision pipeline or a live prime-agent
subscription online 24/7.

Every persisted record is honestly labeled, not passed off as a live verdict:
- `classification`/`state` come from the fixture's own hand-labeled ground
  truth (`evaluation/fixtures/incidents/*/expected.json`) -- the same labels
  M3/M5's real agent-eval runs scored against (docs/eval-m3/m5-*.md), not a
  fabricated-for-this-script guess.
- `narrative_md` is a deterministic template, tagged `[REPLAY DEMO]` and
  explicit that no LLM produced it -- never to be confused with a real
  agent/worker.py narrative.
- `verified_kinematics` for proximity fixtures (two involved tracks) *is*
  real recomputation: `agent.band3.recompute_kinematics` replays the actual
  captured `tracks.jsonl` through the same pairwise-distance math the Band-3
  gate itself uses. Zone/speed fixtures have no pairwise distance to recompute,
  so their verdict carries only the classification.
- `agent_run` reports `model="replay-mode (no LLM call)"`, tokens=0, turns=0
  -- so the dashboard/KPI observability that already tracks agent_runs shows
  these incidents cost nothing, rather than silently miscounting them as real
  agent invocations.

Not a substitute for the real agent pipeline (M3/M4) or the real benchmark/
eval harnesses (M5).
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import random
import shutil
import time
from pathlib import Path

from agent.band3 import load_tracks, recompute_kinematics
from agent.persistence import NullPersister, Persister
from pipelines.config.loader import load_rules
from pipelines.schemas import (
    AgentRunStats,
    Classification,
    IncidentRecord,
    IncidentState,
    KinematicsVerdict,
    TriggerEvent,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES_DIR = REPO_ROOT / "evaluation" / "fixtures" / "incidents"

REPLAY_TAG = "[REPLAY DEMO]"
REPLAY_MODEL_LABEL = "replay-mode (no LLM call)"

_RECOMMENDED_ACTIONS: dict[Classification, list[str]] = {
    Classification.VIOLATION: [
        "Notify site supervisor immediately.",
        "Review the clip and confirm corrective action with the involved worker/operator.",
    ],
    Classification.NEAR_MISS: [
        "Log for shift-report trend review.",
        "No immediate action required; monitor for recurrence.",
    ],
    Classification.NORMAL_OPS: ["No action required."],
    Classification.FALSE_POSITIVE: [
        "No action required; candidate for threshold-tuning review if recurring."
    ],
}


class Fixture:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.event = TriggerEvent.model_validate_json((path / "event.json").read_text("utf-8"))
        expected = json.loads((path / "expected.json").read_text("utf-8"))
        self.expected_state = IncidentState(expected["expected_state"])
        classification = expected.get("expected_classification")
        self.expected_classification = Classification(classification) if classification else None
        self.notes: str = expected.get("notes", "")
        self.tracks_path = path / "tracks.jsonl"


def load_fixtures(fixtures_dir: Path) -> list[Fixture]:
    fixtures = [Fixture(p) for p in sorted(fixtures_dir.iterdir()) if p.is_dir()]
    if not fixtures:
        raise SystemExit(f"no fixtures found under {fixtures_dir}")
    return fixtures


def _build_narrative(fixture: Fixture, citation: str | None, verdict: KinematicsVerdict) -> str:
    lines = [f"{REPLAY_TAG} {fixture.event.rule_id} on {fixture.event.camera_id}."]
    if citation:
        lines.append(f"Cites: {citation}.")
    if verdict.verified_min_distance_m is not None:
        lines.append(f"Recomputed minimum separation: {verdict.verified_min_distance_m:.2f} m.")
    if verdict.closing_velocity_mps is not None:
        lines.append(
            f"Closing velocity at minimum separation: {verdict.closing_velocity_mps:.2f} m/s."
        )
    notes = f" ({fixture.notes})" if fixture.notes else ""
    lines.append(f"Classification: {verdict.classification.value} -- fixture ground truth{notes}.")
    lines.append(
        "This narrative is templated from a pre-labeled fixture for the public demo -- it "
        "was not produced by the LLM agent pipeline (docs/12-roadmap.md M6)."
    )
    return "\n".join(lines)


def build_record(
    fixture: Fixture, rule_citation: str | None, replay_event_id: str
) -> IncidentRecord:
    event = fixture.event
    evidence_refs = [f"incidents/{replay_event_id}/tracks.jsonl"]
    zero_cost_run = AgentRunStats(
        model=REPLAY_MODEL_LABEL, tokens_in=0, tokens_out=0, turns=0, wall_ms=0
    )

    if fixture.expected_state is IncidentState.NEEDS_REVIEW:
        return IncidentRecord(
            event_id=replay_event_id,
            camera_id=event.camera_id,
            trigger_ts=time.time(),
            severity=event.severity_hint,
            state=IncidentState.NEEDS_REVIEW,
            classification=fixture.expected_classification,
            rejection_reason=(
                f"{REPLAY_TAG} {fixture.notes or 'fixture designed to fail the Band-3 gate'}"
            ),
            rule_citations=[event.rule_id],
            evidence_refs=evidence_refs,
            agent_run=zero_cost_run,
        )

    min_distance, closing_velocity = None, None
    if len(event.involved_track_ids) == 2 and fixture.tracks_path.exists():
        frames = load_tracks(fixture.tracks_path)
        track_ids = (event.involved_track_ids[0], event.involved_track_ids[1])
        min_distance, closing_velocity = recompute_kinematics(frames, track_ids)

    classification = fixture.expected_classification or Classification.NORMAL_OPS
    verdict = KinematicsVerdict(
        verified_min_distance_m=min_distance,
        closing_velocity_mps=closing_velocity,
        classification=classification,
        recompute_inputs={"source": "scripts/replay_demo.py (agent.band3.recompute_kinematics)"},
    )

    return IncidentRecord(
        event_id=replay_event_id,
        camera_id=event.camera_id,
        trigger_ts=time.time(),
        severity=event.severity_hint,
        state=IncidentState.CONFIRMED,
        classification=classification,
        verified_kinematics=verdict,
        narrative_md=_build_narrative(fixture, rule_citation, verdict),
        rule_citations=[event.rule_id],
        recommended_actions=_RECOMMENDED_ACTIONS.get(classification, []),
        evidence_refs=evidence_refs,
        agent_run=zero_cost_run,
    )


def stage_evidence(fixture: Fixture, workspace_root: Path, replay_event_id: str) -> None:
    """Mirrors agent/worker.py's own evidence layout (`{workspace_root}/incidents/{event_id}/`)
    so the dashboard's evidence viewer (tracks.jsonl / clip.mp4) works identically for a
    replayed incident -- api/main.py doesn't know or care whether an incident came from a
    real agent run or a replay."""
    dest_dir = workspace_root / "incidents" / replay_event_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    if fixture.tracks_path.exists():
        shutil.copyfile(fixture.tracks_path, dest_dir / "tracks.jsonl")
    clip_src = fixture.path / "clip.mp4"
    if clip_src.exists():
        shutil.copyfile(clip_src, dest_dir / "clip.mp4")


def run(
    fixtures: list[Fixture],
    workspace_root: Path,
    persister: Persister,
    interval_s: float,
    cycles: int,
    shuffle: bool,
    citations: dict[str, str],
) -> None:
    counter = itertools.count(1)
    cycle = 0
    while cycles == 0 or cycle < cycles:
        cycle += 1
        order = list(fixtures)
        if shuffle:
            random.shuffle(order)
        for fixture in order:
            n = next(counter)
            replay_event_id = f"{fixture.event.event_id}_replay_{n:04d}"
            stage_evidence(fixture, workspace_root, replay_event_id)
            citation = citations.get(fixture.event.rule_id)
            record = build_record(fixture, citation, replay_event_id)
            persister.persist(record)
            logger.info(
                "replayed %s -> %s (%s)", replay_event_id, record.state.value, record.classification
            )
            time.sleep(interval_s)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures-dir", default=str(DEFAULT_FIXTURES_DIR))
    ap.add_argument("--workspace-root", default="./workspace")
    ap.add_argument(
        "--postgres-dsn", default=None, help="omit for a dry run (NullPersister, logs only)"
    )
    ap.add_argument(
        "--interval-s", type=float, default=8.0, help="seconds between replayed incidents"
    )
    ap.add_argument("--cycles", type=int, default=0, help="0 = loop forever")
    ap.add_argument("--shuffle", action="store_true", help="randomize fixture order each cycle")
    args = ap.parse_args()

    fixtures = load_fixtures(Path(args.fixtures_dir))
    rules = load_rules()
    citations = {r.id: r.citation for r in rules.rules if r.citation}

    persister: Persister
    if args.postgres_dsn:
        from agent.persistence import PostgresPersister

        persister = PostgresPersister(dsn=args.postgres_dsn)
    else:
        persister = NullPersister()

    logger.info("replay mode: %d fixtures loaded from %s", len(fixtures), args.fixtures_dir)
    run(
        fixtures=fixtures,
        workspace_root=Path(args.workspace_root),
        persister=persister,
        interval_s=args.interval_s,
        cycles=args.cycles,
        shuffle=args.shuffle,
        citations=citations,
    )


if __name__ == "__main__":
    main()
