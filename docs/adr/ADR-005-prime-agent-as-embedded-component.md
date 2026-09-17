# ADR-005: Embed Prime Agent as the Cognitive Plane Runtime

**Status:** Accepted (conditional) · **Details:** docs/prime-agent-feasibility.md,
docs/spikes/spike-01-prime-agent-headless.md (2026-09-17, spike complete)

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

**Spike-01 verdict (2026-09-17): Conditional GO.** 5/5 golden-incident runs (4 local, 1 in the
actual `Dockerfile.agent` container) produced correct, schema-valid `result.json`, including
unprompted Band-3-style discrepancy flagging against the fast path's claimed metrics. Session
persistence confirmed across a hard kill (via the `switch_session` RPC command). **Not** a clean
pass, though: `--autonomous-max-turns` did not stop a non-self-terminating task at 3x its
configured limit, and p50 triage latency ran 82–96 s in 2 of 3 timed runs against a 60 s target.
Neither is a fallback-trigger failure (the core mechanism works, repeatedly, in a real container),
but both change how M3 gets built — see Consequences. Also found: `prime-agent` is not on the
public npm registry (`"private": true`) — `Dockerfile.agent`'s original `npm install -g` would fail
on any machine but this one; fixed with a vendored-tarball interim (`docker/vendor/`), a real
private-registry fix still owed before another contributor or CI can build this image.

## Consequences
+ Agent-as-infrastructure story; computed (not asserted) kinematics; reusable specialist specs;
  native scheduling for shift reports.
+ Fallback preserves the architecture's value if the spike fails.
- Version-pinning discipline and one contract test are mandatory maintenance (feasibility risk F1).
- **`agent/worker.py` must implement its own subprocess-level wall-clock timeout and kill, on top
  of (not instead of) prime-agent's `--autonomous-max-*` flags** — spike-01 found the flags alone
  did not stop a runaway task. This is now a hard requirement for the worker implementation, not
  an optional hardening pass.
- Budget p50 triage latency at 90–120 s for flash-tier models, not 60 s, until a larger sample
  (M5's expanded eval set) says otherwise.
- `docker/vendor/`'s tarball-vendoring is a stopgap; a private registry (GitHub Packages is the
  natural fit) with build-time auth is still owed before this image is reproducible by anyone but
  this machine.
