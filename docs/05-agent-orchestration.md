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
| **Stream Watchdog** (sub-agent, heartbeat) | periodic (60 s) | recent `stream.health` + telemetry stats | offline-camera triage, gap notes (no LLM if all healthy) |
| **Shift Synthesizer** (sub-agent, scheduled) | shift end (cron/heartbeat) | day's incidents + KPI queries via REPL | Markdown/PDF shift audit, KPI table, trend notes |
| **Parameter Reviewer** (sub-agent, rare) | recurring false-positive patterns | rejected-trigger stats | *proposal-only* threshold adjustments (human-approved) |

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
- Scale horizontally by replicas consuming the same queue (visibility timeout 300 s > max triage).
- Session hygiene: `compact` after every N incidents; `new_session` per shift; auto-compaction on.

## 7. Observability

- Per-incident: `get_session_stats` → tokens, turns, wall-clock → `agent_runs` audit table.
- Rejection events (schema or cross-check failure) are first-class metrics — the false-positive
  rate of the whole cognitive plane is dashboard-visible.
- All prompts and outputs stored under `/workspace/incidents/{event_id}/` for replay and eval.
