# 05 — Agent Orchestration (Slow Path)

The cognitive plane is a containerized Prime Agent worker (feasibility and integration contract:
`docs/prime-agent-feasibility.md`). This doc defines *what the agents do*, not *how they are
embedded*.

## 1. Runtime Agent Roles

| Role | Trigger | Input | Output |
| --- | --- | --- | --- |
| **Queue dispatcher** (`worker.py`) | every queued TriggerEvent | event JSON | RPC prompt to root session; schema-validated result to DB |
| **Trajectory & Collision Inspector** (sub-agent) | proximity / TTC-class triggers | tracklet window file + calibration | verified kinematics: min distance, closing velocity, TTC, retreat/advance classification |
| **Compliance Auditor** (sub-agent) | all confirmed incidents | incident evidence + `config/rules.yaml` + shift state | severity, rule citations, OSHA-style narrative, recommended action |
| **Stream Watchdog** (sub-agent, heartbeat) — *optional, M5+* | periodic (60 s) | recent `stream.health` + telemetry stats | offline-camera triage, gap notes (no LLM if all healthy) |
| **Shift Synthesizer** (sub-agent, scheduled) -- **not built**; M4 shipped a deterministic substitute instead (see note below) | shift end (Prime Agent `add_schedule`; shift boundaries from `config/shifts.yaml`) | day's incidents + KPI queries via REPL | Markdown/PDF shift audit, KPI table, trend notes |
| **Parameter Reviewer** (sub-agent, rare) — *optional, M5+* | recurring false-positive patterns | rejected-trigger stats | *proposal-only* threshold adjustments (human-approved) |

**M3 scope is two sub-agents** (trajectory-inspector, compliance-auditor) plus the dispatcher in
`worker.py` (not an agent). Watchdog, synthesizer, and parameter-reviewer land at M5/M4 as
scheduled — keeping M3 aligned with PLAN.md §5.

**M4 update:** what actually shipped for "shift reports" is `api/reports.py` -- a pure-function
HTML renderer that stitches together each confirmed/needs_review incident's own `narrative_md`
(itself already agent-written, per-incident, at triage time) for a time window. It is **not** the
Shift Synthesizer row above: no scheduled agent invocation, no cross-incident KPI-query-via-REPL
synthesis, no new narrative generated at shift end. Building the real Shift Synthesizer is a
separate, not-yet-scoped piece of work (a new sub-agent spec + prompt + eval pair), left open
rather than silently substituted without a note.

## 2. Sub-Agent Specs (persisted in harness)

Each specialist is registered as a harness sub-agent spec so every incident invokes the same
policy without re-prompting:

- `trajectory-inspector`: must verify claims by executing NumPy/SciPy in the REPL against the
  provided tracklet window; output `result.json` (KinematicsVerdict schema); no prose-only answers.
- `compliance-auditor`: cites rule ids from `config/rules.yaml`; never invents regulations;
  severity clamped to enum; output `IncidentRecord.compliance` block.
- `shift-synthesizer`: queries Postgres via REPL (read-only role), computes KPIs, writes
  `reports/shift_{date}.md`; no write access to incident tables.

## 3. Invocation Flow (per incident)

```
worker.py pops TriggerEvent
  -> write payload files: /workspace/incidents/{event_id}/{event.json, tracks.jsonl, clip.mp4}
  -> RPC: new_session (or warm shift session) + prompt (event summary + file paths)
  -> root agent spawns trajectory-inspector (rlm)  [tier-1 flash model]
  -> root agent spawns compliance-auditor          [tier-1 flash model]
  -> root agent merges into result.json            [tier-1; escalate to tier-3 after 2 failures]
  -> worker.py: Pydantic validate + Band-3 recomputation cross-check
  -> pass: Postgres insert + WS push + audit log
  -> fail: state=needs_review, raw evidence retained, rejection logged
```

**M3 implementation note (2026-09-17):** the above is the target design; what `agent/worker.py`
actually ships for M3's exit criterion is a narrower slice of it, verified end-to-end against the
real `prime-agent` CLI (`docs/eval-m3-agent-slow-path.md`) rather than left aspirational. Currently:
one `PrimeAdapter` RPC session per incident, driven with a single role-specific prompt (the
pairwise-distance verification prompt for proximity triggers, a simpler single-track sanity-check
prompt for zone_intrusion/speed) rather than the root session spawning separate
trajectory-inspector/compliance-auditor sub-agents; no `new_session`/shift-session warm-start or
tier escalation yet; Band-3 gating (`agent/band3.py`) is real and enforced exactly as described
above, including the `state=needs_review` + retained-evidence path. Postgres insert isn't wired yet
-- `worker.py` returns/logs a complete `IncidentRecord` and that lands with M4's dashboard/DB work,
not as a gap in the agent pipeline itself. Promoting the two roles to real harness sub-agent specs
(§2) and adding shift-session warm starts are natural M4/M5 follow-ups, not blockers.

## 4. Model Routing (tiers)

| Tier | Model class | Used for | Budget controls |
| --- | --- | --- | --- |
| T1 | GLM-Flash / free-tier (OpenRouter, Z.ai) | all sub-agent execution, routine triage | `--autonomous-max-turns 8`, `max_tokens` per turn |
| T2 | free/flash | watchdog heartbeats | heartbeat period ≥ 60 s |
| T3 | larger GLM/DeepSeek class | escalations (2 failed T1 turns), final shift report | only on escalation path |

Routing is enforced via RPC `set_model` and environment (`OPENAI_BASE_URL`, `PRIME_DEFAULT_MODEL`).

## 5. Scheduling

End-of-shift synthesis uses the agent's own schedule/heartbeat mechanism (RPC `add_schedule` /
`set_heartbeat`) rather than external cron — one fewer moving part, and it keeps the schedule in
the same persistent harness state. Guard: heartbeat prompts must be idempotent and cheap.

## 6. Concurrency & Scaling

- One RPC process per container; one incident in flight per session; queue provides backpressure.
  Queue depth > 20 pending is the scaling/alarm signal.
- Scale horizontally by replicas consuming the same queue (visibility timeout 300 s > max triage).
- Session hygiene: `compact` after every 10 incidents (initial value; tune via
  `get_session_stats` token counts); `new_session` per shift boundary from `config/shifts.yaml`;
  auto-compaction on.

## 7. Observability

- Per-incident: `get_session_stats` → tokens, turns, wall-clock → `agent_runs` audit table.
- Rejection events (schema or cross-check failure) are first-class metrics — the false-positive
  rate of the whole cognitive plane is dashboard-visible.
- All prompts and outputs stored under `/workspace/incidents/{event_id}/` for replay and eval.

## 8. needs_review Workflow

Incidents failing the Band-3 gate are persisted with `state=needs_review`, the rejection reason,
and the raw evidence — never silently dropped. The dashboard exposes a review queue (M4). A human
reviewer either (a) accepts with an override note (row in `reviews`), (b) rejects as false
positive, or (c) re-queues for agent reprocessing, which consumes a fresh incident budget.
The needs_review rate is tracked next to validation pass rate; sustained > 10% triggers a
threshold review (Parameter Reviewer, when enabled).
