from __future__ import annotations

import pytest
from api import repository
from pipelines.schemas import (
    AgentRunStats,
    Classification,
    IncidentRecord,
    IncidentState,
    KinematicsVerdict,
    Severity,
)

pytestmark = pytest.mark.integration


def _record(
    event_id: str = "evt_repo_test", state: IncidentState = IncidentState.CONFIRMED
) -> IncidentRecord:
    return IncidentRecord(
        event_id=event_id,
        camera_id="dock_north_01",
        trigger_ts=1000.0,
        severity=Severity.HIGH,
        state=state,
        classification=Classification.NEAR_MISS if state == IncidentState.CONFIRMED else None,
        verified_kinematics=(
            KinematicsVerdict(
                verified_min_distance_m=1.4,
                closing_velocity_mps=1.1,
                classification=Classification.NEAR_MISS,
            )
            if state == IncidentState.CONFIRMED
            else None
        ),
        rejection_reason=None if state == IncidentState.CONFIRMED else "Band-3 mismatch",
        narrative_md="Worker inside exclusion envelope.",
        rule_citations=["proximity_forklift_pedestrian"],
        evidence_refs=[f"incidents/{event_id}/tracks.jsonl"],
    )


async def test_upsert_and_get_incident_round_trip(pg_pool) -> None:
    record = _record()
    await repository.upsert_incident(pg_pool, record)

    fetched = await repository.get_incident(pg_pool, record.event_id)
    assert fetched is not None
    assert fetched.event_id == record.event_id
    assert fetched.classification == Classification.NEAR_MISS
    assert fetched.verified_kinematics is not None
    assert fetched.verified_kinematics.verified_min_distance_m == 1.4
    assert fetched.rule_citations == ["proximity_forklift_pedestrian"]


async def test_upsert_is_idempotent_on_event_id(pg_pool) -> None:
    needs_review = _record(state=IncidentState.NEEDS_REVIEW)
    await repository.upsert_incident(pg_pool, needs_review)

    confirmed = _record(state=IncidentState.CONFIRMED)
    await repository.upsert_incident(pg_pool, confirmed)  # same event_id -- reprocessed

    incidents = await repository.list_incidents(pg_pool)
    assert len(incidents) == 1
    assert incidents[0].state == IncidentState.CONFIRMED


async def test_get_incident_missing_returns_none(pg_pool) -> None:
    assert await repository.get_incident(pg_pool, "evt_does_not_exist") is None


async def test_list_incidents_filters_by_camera_and_state(pg_pool) -> None:
    await repository.upsert_incident(pg_pool, _record("evt_a", IncidentState.CONFIRMED))
    await repository.upsert_incident(pg_pool, _record("evt_b", IncidentState.NEEDS_REVIEW))

    confirmed_only = await repository.list_incidents(pg_pool, state="confirmed")
    assert [i.event_id for i in confirmed_only] == ["evt_a"]

    by_camera = await repository.list_incidents(pg_pool, camera_id="dock_north_01")
    assert len(by_camera) == 2


async def test_insert_review_updates_and_returns_true(pg_pool) -> None:
    await repository.upsert_incident(pg_pool, _record())
    ok = await repository.insert_review(
        pg_pool, "evt_repo_test", "chris", "accepted", "confirmed by cctv"
    )
    assert ok is True


async def test_insert_review_missing_incident_returns_false(pg_pool) -> None:
    ok = await repository.insert_review(pg_pool, "evt_nope", "chris", "accepted", None)
    assert ok is False


async def test_insert_agent_run_links_to_incident(pg_pool) -> None:
    await repository.upsert_incident(pg_pool, _record())
    stats = AgentRunStats(
        model="glm-flash", tokens_in=8000, tokens_out=1500, turns=4, wall_ms=75000
    )
    await repository.insert_agent_run(pg_pool, "evt_repo_test", "confirmed", stats)

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM agent_runs WHERE event_id = $1", "evt_repo_test")
    assert row is not None
    assert row["incident_id"] is not None
    assert row["tokens_in"] == 8000


async def test_insert_agent_run_without_incident_is_allowed(pg_pool) -> None:
    """A crashed/timed-out run has no IncidentRecord yet -- still logged
    (docs/05 §7: failure visibility matters more than success visibility)."""
    await repository.insert_agent_run(pg_pool, "evt_never_confirmed", "timeout", None)

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM agent_runs WHERE event_id = $1", "evt_never_confirmed"
        )
    assert row is not None
    assert row["incident_id"] is None
    assert row["status"] == "timeout"


async def test_kpis_aggregates_by_classification_and_state(pg_pool) -> None:
    await repository.upsert_incident(pg_pool, _record("evt_a", IncidentState.CONFIRMED))
    await repository.upsert_incident(pg_pool, _record("evt_b", IncidentState.NEEDS_REVIEW))

    result = await repository.kpis(pg_pool, window_hours=1e9)  # wide window, catches ts=1000.0
    assert result["total_incidents"] == 2
    assert result["by_state"]["confirmed"] == 1
    assert result["by_state"]["needs_review"] == 1
    assert result["by_classification"]["near_miss"] == 1
