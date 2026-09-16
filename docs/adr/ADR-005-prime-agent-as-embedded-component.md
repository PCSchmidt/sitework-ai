# ADR-005: Embed Prime Agent as the Cognitive Plane Runtime

**Status:** Accepted, contingent on M3.0 spike · **Details:** docs/prime-agent-feasibility.md

## Context
The cognitive plane needs: an agent that verifies claims by executing code (REPL), persistent
specialist sub-agents, scheduled autonomous synthesis, cheap model routing, and headless
containerized operation. Prime Agent (the author's product) provides all of these — and, verified
against the installed package, exposes headless integration surfaces: JSON-lines **RPC mode**
(prompt/steer/set_model/heartbeats/schedules/stats), single-shot print mode, and hard autonomous
budget flags (`--autonomous-max-turns/-max-tokens/-timeout-ms`).

## Decision
Embed Prime Agent as the slow-path runtime:
- One `prime-agent --mode rpc` process per agent container, driven by `agent/worker.py`.
- All invocation behind `agent/prime_adapter.py`; pinned version; golden-session contract test in CI.
- Harness state persisted on a volume at `/root/.prime`; results handed off as `result.json` files
  validated by Pydantic (Band-3 gate) — files, not chat text, are the machine contract.
- Contingency: M3.0 two-day spike must demonstrate validated output + budget enforcement + state
  persistence. Fallback: `agent/worker_fallback.py` (plain LiteLLM agent loop) behind the same
  queue-to-schema contracts.

## Consequences
+ Agent-as-infrastructure story; computed (not asserted) kinematics; reusable specialist specs;
  native scheduling for shift reports.
+ Fallback preserves the architecture's value if the spike fails.
- Version-pinning discipline and one contract test are mandatory maintenance (feasibility risk F1).
