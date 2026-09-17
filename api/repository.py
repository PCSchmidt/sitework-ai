"""asyncpg queries backing the REST/WS API and agent/worker.py's persistence hook.

`IncidentRecord`/`AgentRunStats` (pipelines/schemas) are the wire format in
both directions -- this module only translates them to/from SQL rows, never
invents its own shape for the same data (docs/06's "single source of truth"
rule applies to the DB boundary too, not just the fast/slow one).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import asyncpg
from pipelines.schemas import AgentRunStats, IncidentRecord, IncidentState, KinematicsVerdict


def _row_to_incident(row: asyncpg.Record) -> IncidentRecord:
    verified_kinematics = None
    if row["verified_kinematics"] is not None:
        verified_kinematics = KinematicsVerdict.model_validate(
            json.loads(row["verified_kinematics"])
        )
    return IncidentRecord(
        event_id=row["event_id"],
        camera_id=row["camera_id"],
        trigger_ts=row["trigger_ts"],
        severity=row["severity"],
        state=IncidentState(row["state"]),
        classification=row["classification"],
        verified_kinematics=verified_kinematics,
        rejection_reason=row["rejection_reason"],
        narrative_md=row["narrative_md"],
        rule_citations=list(row["rule_citations"]),
        recommended_actions=list(row["recommended_actions"]),
        evidence_refs=list(row["evidence_refs"]),
    )


async def upsert_incident(pool: asyncpg.Pool, record: IncidentRecord) -> None:
    """Insert, or update in place on a re-processed event_id (docs/05 §6:
    XAUTOCLAIM can hand a stale entry to a second consumer after a crash --
    that consumer's result should replace, not duplicate, the first one)."""
    verified_kinematics_json = (
        record.verified_kinematics.model_dump_json() if record.verified_kinematics else None
    )
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO incidents (
                event_id, camera_id, trigger_ts, severity, state, classification,
                verified_kinematics, rejection_reason, narrative_md, rule_citations,
                recommended_actions, evidence_refs
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (event_id) DO UPDATE SET
                state = EXCLUDED.state,
                classification = EXCLUDED.classification,
                verified_kinematics = EXCLUDED.verified_kinematics,
                rejection_reason = EXCLUDED.rejection_reason,
                narrative_md = EXCLUDED.narrative_md,
                rule_citations = EXCLUDED.rule_citations,
                recommended_actions = EXCLUDED.recommended_actions,
                evidence_refs = EXCLUDED.evidence_refs
            """,
            record.event_id,
            record.camera_id,
            record.trigger_ts,
            str(record.severity),
            str(record.state),
            str(record.classification) if record.classification else None,
            verified_kinematics_json,
            record.rejection_reason,
            record.narrative_md,
            record.rule_citations,
            record.recommended_actions,
            record.evidence_refs,
        )


async def get_incident(pool: asyncpg.Pool, event_id: str) -> IncidentRecord | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM incidents WHERE event_id = $1", event_id)
    return _row_to_incident(row) if row else None


async def list_incidents(
    pool: asyncpg.Pool,
    *,
    ts_from: float | None = None,
    ts_to: float | None = None,
    severity: str | None = None,
    camera_id: str | None = None,
    state: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[IncidentRecord]:
    clauses: list[str] = []
    args: list[Any] = []

    def add(clause: str, value: Any) -> None:
        args.append(value)
        clauses.append(clause.format(n=len(args)))

    if ts_from is not None:
        add("trigger_ts >= ${n}", ts_from)
    if ts_to is not None:
        add("trigger_ts <= ${n}", ts_to)
    if severity is not None:
        add("severity = ${n}", severity)
    if camera_id is not None:
        add("camera_id = ${n}", camera_id)
    if state is not None:
        add("state = ${n}", state)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.extend([limit, offset])
    query = (
        f"SELECT * FROM incidents {where} "
        f"ORDER BY trigger_ts DESC LIMIT ${len(args) - 1} OFFSET ${len(args)}"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
    return [_row_to_incident(r) for r in rows]


async def insert_review(
    pool: asyncpg.Pool, event_id: str, reviewer: str, decision: str, note: str | None
) -> bool:
    """Records a human review decision (docs/05 §8). Returns False if
    `event_id` doesn't exist rather than raising -- a 404 is the caller's
    (API route's) call to make."""
    async with pool.acquire() as conn:
        incident_id = await conn.fetchval(
            "SELECT id FROM incidents WHERE event_id = $1", event_id
        )
        if incident_id is None:
            return False
        await conn.execute(
            "INSERT INTO reviews (incident_id, reviewer, decision, note) VALUES ($1, $2, $3, $4)",
            incident_id,
            reviewer,
            decision,
            note,
        )
    return True


async def insert_agent_run(
    pool: asyncpg.Pool,
    event_id: str,
    status: str,
    stats: AgentRunStats | None,
    kind: str = "trajectory_inspector",
) -> None:
    """Logged for every attempt, confirmed or not (docs/05 §7): the agent's
    false-positive/failure rate has to be visible even when no IncidentRecord
    exists yet (e.g. incident_id resolves after upsert_incident runs first)."""
    async with pool.acquire() as conn:
        incident_id = await conn.fetchval(
            "SELECT id FROM incidents WHERE event_id = $1", event_id
        )
        await conn.execute(
            """
            INSERT INTO agent_runs (
                incident_id, event_id, kind, model, tokens_in, tokens_out, turns, wall_ms, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            incident_id,
            event_id,
            kind,
            stats.model if stats else None,
            stats.tokens_in if stats else 0,
            stats.tokens_out if stats else 0,
            stats.turns if stats else 0,
            stats.wall_ms if stats else 0,
            status,
        )


async def kpis(pool: asyncpg.Pool, window_hours: float = 24.0) -> dict[str, Any]:
    """docs/06 §4 `GET /kpis?window=`: near-miss rate, state breakdown."""
    async with pool.acquire() as conn:
        cutoff = datetime.now().timestamp() - window_hours * 3600
        rows = await conn.fetch(
            """
            SELECT classification, state, count(*) AS n
            FROM incidents
            WHERE trigger_ts >= $1
            GROUP BY classification, state
            """,
            cutoff,
        )
    by_classification: dict[str, int] = {}
    by_state: dict[str, int] = {}
    total = 0
    for row in rows:
        n = row["n"]
        total += n
        if row["classification"]:
            by_classification[row["classification"]] = (
                by_classification.get(row["classification"], 0) + n
            )
        by_state[row["state"]] = by_state.get(row["state"], 0) + n
    return {
        "window_hours": window_hours,
        "total_incidents": total,
        "by_classification": by_classification,
        "by_state": by_state,
    }
