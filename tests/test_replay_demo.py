"""scripts/replay_demo.py (docs/12 M6: simulated-live replay mode)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pipelines.schemas import Classification, IncidentRecord, IncidentState
from scripts.replay_demo import (
    DEFAULT_FIXTURES_DIR,
    REPLAY_TAG,
    Fixture,
    build_record,
    load_fixtures,
    run,
    stage_evidence,
)


class _RecordingPersister:
    def __init__(self) -> None:
        self.records: list[IncidentRecord] = []
        self.crashes: list[str] = []

    def persist(self, record: IncidentRecord) -> None:
        self.records.append(record)

    def persist_crash(self, event_id: str) -> None:
        self.crashes.append(event_id)


def test_load_fixtures_finds_all_30_seeded_incidents() -> None:
    fixtures = load_fixtures(DEFAULT_FIXTURES_DIR)
    assert len(fixtures) == 30
    assert all(isinstance(f, Fixture) for f in fixtures)


def _fixture(event_id: str) -> Fixture:
    fixtures = load_fixtures(DEFAULT_FIXTURES_DIR)
    matches = [f for f in fixtures if f.event.event_id == event_id]
    assert matches, f"no fixture named {event_id}"
    return matches[0]


def test_build_record_proximity_violation_recomputes_real_distance() -> None:
    fixture = _fixture("evt_seed_violation_01")
    assert fixture.expected_state is IncidentState.CONFIRMED
    assert fixture.expected_classification is Classification.VIOLATION

    record = build_record(fixture, "SITE-POLICY-3.1 (test citation)", "replay_test_01")

    assert record.event_id == "replay_test_01"
    assert record.state is IncidentState.CONFIRMED
    assert record.classification is Classification.VIOLATION
    assert record.verified_kinematics is not None
    # Recomputed from the fixture's own tracks.jsonl (agent.band3 math), not
    # copied from event.json -- happens to match the seeded metrics here
    # because build_seed_incidents.py seeds tracks consistent with them.
    assert record.verified_kinematics.verified_min_distance_m == pytest.approx(0.7, abs=0.01)
    assert REPLAY_TAG in record.narrative_md
    assert record.agent_run is not None
    assert record.agent_run.tokens_in == 0
    assert record.agent_run.tokens_out == 0
    assert record.agent_run.model == "replay-mode (no LLM call)"
    assert record.recommended_actions  # violation gets real recommended actions


def test_build_record_needs_review_fixture_carries_no_fabricated_classification() -> None:
    fixture = _fixture("evt_seed_evidence_inconsistent_01")
    assert fixture.expected_state is IncidentState.NEEDS_REVIEW
    assert fixture.expected_classification is None

    record = build_record(fixture, None, "replay_test_02")

    assert record.state is IncidentState.NEEDS_REVIEW
    assert record.classification is None
    assert record.rejection_reason is not None
    assert record.rejection_reason.startswith(REPLAY_TAG)
    assert record.verified_kinematics is None


def test_build_record_zone_fixture_has_no_pairwise_distance() -> None:
    fixture = _fixture("evt_seed_zone_violation_01")
    record = build_record(fixture, "SITE-POLICY-4.2 (test citation)", "replay_test_03")

    assert record.verified_kinematics is not None
    assert record.verified_kinematics.verified_min_distance_m is None
    assert record.verified_kinematics.closing_velocity_mps is None
    assert record.classification is Classification.VIOLATION


def test_stage_evidence_copies_tracks_to_workspace_layout(tmp_path: Path) -> None:
    fixture = _fixture("evt_seed_violation_01")
    stage_evidence(fixture, tmp_path, "replay_test_04")

    dest = tmp_path / "incidents" / "replay_test_04" / "tracks.jsonl"
    assert dest.exists()
    assert dest.read_text("utf-8") == fixture.tracks_path.read_text("utf-8")


def test_run_persists_every_fixture_exactly_once_per_cycle(tmp_path: Path) -> None:
    fixtures = load_fixtures(DEFAULT_FIXTURES_DIR)
    persister = _RecordingPersister()

    run(
        fixtures=fixtures,
        workspace_root=tmp_path,
        persister=persister,
        interval_s=0.0,
        cycles=1,
        shuffle=False,
        citations={},
    )

    assert len(persister.records) == len(fixtures)
    assert len({r.event_id for r in persister.records}) == len(fixtures)
    assert not persister.crashes


def test_run_two_cycles_produces_distinct_event_ids(tmp_path: Path) -> None:
    fixtures = load_fixtures(DEFAULT_FIXTURES_DIR)[:3]
    persister = _RecordingPersister()

    run(
        fixtures=fixtures,
        workspace_root=tmp_path,
        persister=persister,
        interval_s=0.0,
        cycles=2,
        shuffle=False,
        citations={},
    )

    assert len(persister.records) == 6
    assert len({r.event_id for r in persister.records}) == 6
