# Feasibility: Prime Agent as an Application Component

**Question:** can Prime Agent (github.com/PCSchmidt/prime-agent) be more than the tool that
*builds* SiteWatch AI — can it be a **deployed component of the running application**, inside a
Docker container, processing live incident events?

**Verdict: Yes — feasible today, with named caveats and a built-in fallback.** This doc is the
evidence-based analysis. Verified against the installed Prime Agent package
(`prime-agent` npm distribution, inspected directly).

---

## 1. What Makes Prime Agent Uniquely Suited Here

Most "agent frameworks" in a CV pipeline would just be an LLM API call. Prime Agent brings four
capabilities that map directly onto SiteWatch's cognitive plane:

1. **A persistent IPython REPL kernel as the agent's native tool.** The incident verifier does not
   *claim* "closing velocity was 2.3 m/s" — it executes NumPy/SciPy against the stored tracklet
   window and the answer is computed, not hallucinated. This is the core of the hybrid design
   (docs/03-hybrid-design.md): probabilistic reasoning with deterministic verification.
2. **Recursive sub-agents as cheap async calls.** `await rlm(...)` spawns isolated specialist
   sessions (trajectory inspector, compliance auditor) with A2A messaging and its own kernels —
   exactly the runtime MAS from the original concept (see `project_concepts_ideas.md`).
3. **Continual harness state.** Sub-agent specs, memories, and refined behavioral policies persist
   on disk (`/home/node/.prime/agent/`). Specialist roles are refined once and reused across every
   incident and across container restarts when the directory is a persistent volume.
4. **Model-agnostic routing.** OpenAI-compatible base URL (OpenRouter / Z.ai / local vLLM) means
   the whole agent pool can run on GLM-Flash-class models at fractions of a cent per incident.

## 2. Verified Programmatic Surfaces (the feasibility evidence)

Inspection of the installed package (`dist/modes/`, `dist/cli/`) confirms three embeddable
invocation tiers, from thinnest to richest:

### Tier A — Print mode (single-shot, simplest)
`dist/modes/print-mode.d.ts`: "Print mode (single-shot): Send prompts, output result, exit."
Supports `--mode text` (final response only) or `--mode json` (full JSON event stream), multiple
prompts, and image attachments.

- SiteWatch use: stateless per-incident triage. The queue consumer (`agent/worker.py`) builds a
  prompt containing the TriggerEvent JSON + telemetry file path, invokes
  `prime-agent --mode json --no-session -p "<payload>"`, parses the JSON event stream for the final
  assistant message, validates against the IncidentRecord schema.
- Pros: process-isolated, trivially retryable, no daemon state to manage.
  Cons: pays session startup each time; no intra-session memory.

### Tier B — RPC mode (primary integration path) ✅ recommended
`dist/modes/rpc/rpc-types.d.ts` defines a **JSON-lines RPC protocol over stdin/stdout for headless
operation**. Verified commands include:

| RPC command | SiteWatch use |
| --- | --- |
| `prompt`, `follow_up`, `steer` | Deliver incident payload; steer an in-flight triage with new telemetry |
| `new_session` | Fresh session per incident (or reuse a warm session per shift) |
| `set_model`, `get_available_models` | Tier routing (flash worker → frontier escalation) |
| `get_last_assistant_text`, `get_messages` | Retrieve the triage result for schema validation |
| `get_session_stats` | Token/turn accounting per incident (cost telemetry) |
| `bash` | Health checks inside the container |
| `list_heartbeats` / `set_heartbeat` / `add_schedule` | Scheduled end-of-shift synthesis — no external cron needed |
| `compact`, `set_auto_compaction` | Context hygiene on long-lived sessions |

The integration: the `agent` container runs one long-lived `prime-agent --mode rpc` process;
`agent/worker.py` consumes the queue and speaks JSON lines to its stdin/stdout. This is a *real
IPC contract*, not screen-scraping.

### Tier C — Daemon mode
`--mode daemon` + socket for attach/observe. Use case: a shared daemon serving multiple worker
containers. More moving parts; document as an option, don't build on it first.

### Hard budget controls (verified CLI flags)
`dist/cli/args.d.ts` exposes exactly the guardrails the cost model requires:

```
prime-agent --mode rpc \
  --autonomous --autonomous-max-turns 8 --autonomous-max-tokens 50000 \
  --autonomous-timeout-ms 120000 --autonomous-gates <...> \
  --tools <allowlist> --skills <allowlist> --no-builtin-tools ... \
  --cwd /workspace --append-system-prompt <operating-policy>
```

`--autonomous-max-turns`, `--autonomous-max-tokens`, `--autonomous-timeout-ms` map 1:1 onto the
trigger-rate and loop-protection requirements in docs/10-cost-model.md. `--tools`/`--skills`
allowlists and `--no-session` support least-privilege configuration per deployment.

## 3. Proposed Runtime Topology

```
[Queue: anomaly events]                                [Schedule: shift end]
        |                                                      |
        v                                                      v
+---------------------------------------------------------------+
| agent container (docker/Dockerfile.agent)                     |
|  worker.py  --JSON-lines-RPC-->  prime-agent --mode rpc       |
|                                    |- IPython REPL (numpy/scipy)
|                                    |- rlm() sub-agents:        |
|                                    |   trajectory-inspector    |
|                                    |   compliance-auditor      |
|                                    |   shift-synthesizer       |
|  volumes: /home/node/.prime (persistent harness state)             |
|           /workspace/incidents (event payloads, result JSON)  |
+---------------------------------------------------------------+
        |
        v
[Postgres incidents table]  <-- validated IncidentRecord only
```

**Result hand-off contract:** sub-agents and root turns are instructed to write structured results
to `/workspace/incidents/{event_id}/result.json`; `worker.py` validates with the Pydantic schema
before any DB write. Files, not chat text, are the machine-readable fan-in contract — this avoids
parsing freeform agent prose.

### Docker image requirements (from the installed package's own structure)
- Node.js ≥ 22.8.0 (TypeScript supervisor/daemon; `package.json`'s own `engines.node` --
  corrected from an initial ≥20 guess by spike-01 Finding 2, which hit an `EBADENGINE` warning
  against `node:20`) **and** Python ≥ 3.11 with `uv` (the bundled `prime-agent-runtime` pyproject
  requires `>=3.11`; kernel-side shim uses `mcp`, `tyro`).
- Persistent volume mount at `/home/node/.prime` (or configured state dir) for harness memory,
  refined sub-agent specs, and session trees — matches the EFS/Filestore/Azure-Files design in the
  cloud runbooks.
- Non-root user, dropped capabilities, egress restricted to broker + LLM endpoints (docs/08-security.md).

## 4. Honest Risk Assessment

| # | Risk | Severity | Evidence / Mitigation |
| --- | --- | --- | --- |
| F1 | **Interface drift** — prime-agent evolves; RPC/print contracts change between versions | High | Pin an exact version/commit in `Dockerfile.agent`; wrap all invocation in one adapter module `agent/prime_adapter.py`; CI contract test replays a golden RPC session against the pinned version |
| F2 | **Model-generated code execution** inside the container | High (contained) | Container isolation is the sandbox: non-root, CAP_DROP_ALL, read-only rootfs except state/workspace volumes, no k8s/cloud credentials in the container, egress allowlist. Incident payload fields are data, never executed; system prompt forbids shell/interactive use |
| F3 | **Prompt injection via telemetry** — camera/zone names or track labels could carry adversarial text | Medium | Sanitize/escape all payload strings; allowlist field enums (class names, rule ids); agent policy: telemetry is data to analyze, not instructions to obey |
| F4 | **Latency** — a triage turn is seconds-to-tens-of-seconds | Accepted | By design: async slow path. Deterministic alerts (docs/03) never wait for the agent |
| F5 | **Freeform output parsing** | Medium | result.json file contract + Pydantic validation + Band-3 recomputation cross-check (docs/03-hybrid-design.md §3); unparseable ⇒ `needs_review` state, never garbage in DB |
| F6 | **Flash-class model tool discipline** (markdown blocks instead of executing, `input()` attempts) | Medium | Known caveat from the concept doc; strict harness policy (non-interactive, single-pass scripts), 2-strike escalation to a stronger model via `set_model` RPC |
| F7 | **Cost runaway** on autonomous loops | Medium | **Revised by spike-01 Finding 4:** `--autonomous-max-*` flags alone did NOT stop a runaway task (observed 9 turns/130+s against `--autonomous-max-turns 3`). Real mitigation is `PrimeAdapter`'s own external wall-clock timeout + kill (`agent/prime_adapter.py`), with the CLI flags as a secondary, not sole, layer; plus per-incident token accounting (`get_session_stats`) + queue-depth budget alarm (docs/10-cost-model.md) |
| F8 | **Windows/local dev divergence** | Low | Agent always runs in Linux containers, locally and in reference architecture; host OS irrelevant |
| F9 | **License/distribution** — it's the author's own product | **Elevated Low → real by spike-01 Finding 1** | `prime-agent`'s `package.json` has `"private": true` — it is NOT on the public npm registry, so `Dockerfile.agent`'s original `npm install -g` fails on any machine but one with it already installed globally. Interim: vendored tarball install (`docker/vendor/`, gitignored, regeneration steps in `docker/vendor/README.md`). Real fix still owed: a private registry (GitHub Packages is the natural fit) with build-time auth, before this image is reproducible by anyone but the author's machine or CI with that auth configured |

## 5. De-risking Spike (M3.0 — first task of Milestone 3, ~2 days)

Before committing to the RPC integration, run a time-boxed spike and record results in
`docs/spikes/spike-01-prime-agent-headless.md`:

1. Build `Dockerfile.agent`; run `prime-agent --mode rpc` in the container; drive it from Python
   over stdin/stdout (prompt → get_last_assistant_text).
2. One golden incident: hand the agent a TriggerEvent + tracklet JSON file; require it to compute
   min distance via the REPL and write `result.json`; validate with the Pydantic schema.
3. Measure: wall-clock per incident, tokens per incident, cold vs warm session.
4. Verify budget flags actually stop runaway turns (feed a prompt designed to loop, confirm
   `--autonomous-max-turns` halts it).
5. Kill the container mid-triage; restart; confirm harness state persisted on the volume.

**Pass criteria:** validated result.json produced; p50 triage ≤ 60 s; tokens/incident ≤ budget;
state survives restart. **Fallback if it fails:** the identical queue→schema contracts are served
by a plain LiteLLM agent-loop worker (`agent/worker_fallback.py`); the system's value proposition
(schema boundary, deterministic gates, dashboards) survives unchanged — Prime Agent is the
differentiator, not a single point of failure. This is recorded as ADR-005.

## 6. Why It's Worth It (portfolio framing)

A reviewer sees: "the agent that built the system is also the reasoning component of the system,
running headless in a container, computing its own verification math in a sandboxed REPL." That is
a rare, concrete demonstration of agentic systems engineering — agent-as-infrastructure, not
agent-as-chatbot. The RPC contract and budget flags make it defensible as engineering, not novelty.
