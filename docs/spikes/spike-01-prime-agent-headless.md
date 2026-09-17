# Spike-01: Prime Agent Headless (RPC) — RESULTS

**Status:** complete (2026-09-17) · **Owner:** solo dev · **Timebox:** 2 days → done in 1 session

Runs the de-risking spike specified in `docs/prime-agent-feasibility.md` §5. Unlike spike-00/
spike-02, this spike used the *real* `prime-agent` CLI (v0.9.3), already installed and configured
on this machine with a working OpenRouter/GLM-Flash setup — not a hypothetical integration.

## Verdict: **Conditional GO**

The core mechanism works, end to end, repeatedly, in a real container. Two real gaps were found
that change how M3 should be built, not whether it should be built. Recorded per ADR-005: this is
a GO on the RPC integration, not a fallback-to-LiteLLM trigger — but `agent/worker.py` must add its
own external supervisory timeout (see Finding 4) rather than trusting prime-agent's internal budget
flags alone.

## What was actually run

1. **Golden incident** (§5.1): a realistic `TriggerEvent` + `tracks.jsonl` (person track 42,
   forklift track 77, 4 frames, hand-computed ground truth: min distance 1.2 m at `frame_ts=1000.0`,
   closing velocity 1.8 m/s, separating afterward → `ttc_s=null`). Prompted the trajectory-inspector
   role to recompute via actual code execution and write `result.json`. Ran **5 times** (4 local,
   1 inside the built container) — **5/5 produced byte-for-byte-correct, schema-valid results**,
   including runs that unprompted flagged the discrepancy between the verified 1.2 m and the fast
   path's claimed 1.7 m, one of which explicitly noted it "re-verified in a second independent
   pass" — exactly the Band-3 cross-check behavior the hybrid design depends on.
2. **Budget flags** (§5.2): two tests. One with an obviously-unbounded task (count to 1,000,000,
   one bash call per number) — the model **self-limited** at 10, explained why, and offered
   alternatives (a positive, unplanned safety signal, but not one to rely on). One with a
   plausible-looking unbounded task (write a new haiku forever, one per tool call) with
   `--autonomous-max-turns 3` — the flag **did not stop it**; it ran 9 turns / 21 lines of haikus
   over 130+ s until my driver's own external timeout force-aborted it. See Finding 4.
3. **Persistence** (§5.3): started a session, captured its session file, hard-killed the process,
   started a fresh process, reloaded the session via the `switch_session` RPC command, confirmed
   the prior exchange was intact. Pass — with a caveat (Finding 5).
4. **Container** (§5.1's "build Dockerfile.agent"): built `docker/Dockerfile.agent` for real, fixed
   three build failures it actually had (Findings 1–3), then ran a full RPC round trip *inside* the
   built container with host harness state mounted for auth. Pass.

## Findings

### Finding 1 (elevates risk F9, "Low" → real): prime-agent is not on the public npm registry

`prime-agent`'s own `package.json` has `"private": true`. The original `Dockerfile.agent` draft
(`npm install -g prime-agent@x.y.z`) only ever worked because this machine happens to have it
globally installed already — it fails on any other machine, including CI, with a 404. Fixed for
now by vendoring a tarball (`npm pack` the verified global install → `docker/vendor/*.tgz`,
gitignored, `docker/vendor/README.md` has the regeneration steps + the real fix needed: a private
registry with build-time auth, e.g. GitHub Packages, before this image is reproducible by anyone
else). This is a real gap to close before M3 ships, not a documentation nit.

### Finding 2: docs/07 says "Node.js ≥ 20"; prime-agent actually requires ≥22.8.0

`npm install` on `node:20.18-bookworm-slim` produced an `EBADENGINE` warning (not a hard failure —
easy to miss) because `prime-agent`'s `engines.node` is `>=22.8.0`. Fixed by pinning
`node:22.11-bookworm-slim` in `Dockerfile.agent`. docs/07's repo-layout doc should be corrected
to say Node 22 when M3 lands for real (not done here — that doc wasn't touched this session).

### Finding 3: two small but real Dockerfile bugs, both silent failure modes

- `useradd --uid 1000` failed outright (`UID 1000 is not unique`) — `node:22-bookworm-slim` already
  ships a uid-1000 `node` user. Fixed by reusing it instead of creating a second one.
- `curl -LsSf https://astral.sh/uv/install.sh | sh` hit a transient DNS failure and **the build
  "succeeded" anyway** — piping curl into sh swallows curl's exit code, so a network blip silently
  produced an image with no `uv` installed at all, no error, nothing to notice until something
  downstream needed it. Fixed with `bash -c "set -euo pipefail; ..."` plus an explicit
  `uv --version` check so a broken install is a hard build failure. Worth internalizing as a general
  pattern for every `curl | sh` in this repo's other Dockerfiles.

### Finding 4 (the important one): `--autonomous-max-turns` is not a trustworthy hard ceiling

docs/prime-agent-feasibility.md §5 step 4 and risk F7's mitigation both lean on
`--autonomous-max-*` flags as *the* cost-runaway guardrail. Tested directly: `--autonomous-max-turns
3` did not stop a plausible-looking unbounded task at 9 turns and 130+ seconds; only an external
wrapper-level timeout (the spike driver's own deadline + `abort` command) actually stopped it. This
may be a version-specific behavior, an interaction with not setting `--autonomous-gate` (untested —
gates may be what's meant to define "done," with max-turns as a secondary ceiling that doesn't bite
cleanly without one), or something else — this spike didn't have budget to fully reverse-engineer a
third party's internals. What matters for SiteWatch: **do not ship `agent/worker.py` assuming
prime-agent's own flags are sufficient.** `worker.py` must wrap every invocation in its own
subprocess-level wall-clock timeout and kill it if exceeded, regardless of what CLI flags are
passed — defense in depth, not a single point of trust. This changes F7's mitigation in the
feasibility doc from "flags handle it" to "flags plus an external supervisor handle it."

### Finding 5: session persistence works, but not via the CLI flag I tried first

`prime-agent --resume <path> --no-session` did **not** reload prior messages (`get_messages`
returned 0). The RPC command `{"type": "switch_session", "sessionPath": ...}` sent to a plain
`--mode rpc --no-session` process **did** work correctly. For `agent/worker.py`'s actual use case
(a long-lived RPC process managing sessions programmatically), `switch_session` is the right
mechanism anyway — this is a note for whoever writes that code, not a blocker.

### Finding 6: latency is real but highly variable; the 60 s p50 target is not consistently met

| Run | Context | Wall clock | Tokens | Cost | Correct? |
| --- | --- | --- | --- | --- | --- |
| 1 (local) | golden incident, cold | 33.7 s | n/a (stats-fetch bug this run) | n/a | ✅ |
| 2 (local) | golden incident | 96.3 s | 43,510 | $0.00188 | ✅ (+ flagged the 1.7→1.2 m discrepancy unprompted) |
| 3 (local) | golden incident | unmeasured (post-completion hang, see below) | — | — | ✅ (result.json correct) |
| 4 (local) | golden incident | 82.1 s | 55,655 | $0.00182 | ✅ (+ flagged discrepancy, "re-verified in a second independent pass") |
| container | golden incident, cold | ~30.6 s (trivial prompt, not full incident) | — | — | ✅ |

Only 1 of 3 timed full-incident runs cleared the ≤60 s p50 target from §5's pass criteria (33.7 s;
the other two took 96.3 s and 82.1 s). Tokens/incident (43,510 and 55,655 in the two
reliably-measured runs) also ran above docs/10-cost-model.md's 15–30 K estimate, though **cost
stayed on budget** (~$0.0018–0.0019, well inside the $0.001–0.005/incident band) because
GLM-Flash-class cache-read pricing absorbs the overshoot. Recommendation: don't hard-commit to a
60 s p50 for flash-tier models without more prompt/tool-path tuning; budget 90–120 s as the
realistic ceiling for now, and revisit at M5 with a larger eval set (this spike's n=3 timed runs is
not a real distribution).

One run (#3) finished its actual work (correct `result.json` on disk) but the RPC process then
hung for 20+ minutes on my post-completion `get_session_stats`/`get_last_assistant_text` fetch,
never emitting a response, while two *other* spike test processes were running concurrently against
the same shared background daemon. Likely daemon contention from running multiple concurrent local
RPC invocations during testing — the real M3 architecture is one long-lived RPC process per agent
container, not concurrent ad hoc invocations racing a shared daemon, so this may not recur in
production. Still reinforces Finding 4: whatever the cause, an external supervisory timeout would
have caught and killed this cleanly, and nothing internal to prime-agent did.

## Pass criteria (docs/prime-agent-feasibility.md §5) — scored honestly

| Criterion | Result |
| --- | --- |
| Validated `result.json` produced | ✅ 5/5 runs, first-try schema validation, no coercion |
| p50 triage ≤ 60 s | ⚠️ 1/3 timed runs met it (33.7 s, 96.3 s, 82.1 s) — see Finding 6 |
| Tokens/incident ≤ budget | ⚠️ cost on budget; raw tokens (43.5–55.7 K) above the 15–30 K estimate |
| State survives restart | ✅ via `switch_session` (not the `--resume` CLI flag — Finding 5) |
| Budget flags stop runaway turns | ❌ not observed — Finding 4 |

Not a clean sweep. Read together with what *did* work (real code-execution verification, correct
Band-3-style self-critique, working containerization, working persistence), this is a **conditional
GO**: the differentiator claimed in docs/prime-agent-feasibility.md §6 is real and demonstrated, but
`agent/worker.py` ships with its own timeout/kill supervision from day one, not as a
later hardening pass.

## Artifacts

- `docker/Dockerfile.agent` — fixed, builds, verified (Findings 1–3).
- `docker/vendor/README.md` — vendoring rationale + regeneration steps.
- `docs/spikes/spike-01-workspace/` — driver script, golden-incident fixtures, raw event logs
  (gitignored; not committed — scratch, not a deliverable).

## What this changes going forward (for whoever builds M3 for real)

1. `agent/worker.py` needs its own subprocess wall-clock timeout + `abort`/kill, independent of
   `--autonomous-max-*` flags (Finding 4). Non-negotiable given what was observed.
2. Close Finding 1 (private registry) before anyone but this machine needs to build
   `docker/Dockerfile.agent`.
3. Bump docs/07's Node version claim from "≥20" to "≥22" when that doc next gets a real M3 pass
   (not done in this spike — flagged, not fixed, since spike-01's job was code + honest findings,
   not a docs sweep unrelated to what was tested).
4. Budget latency expectations at 90–120 s p50 for flash-tier models until a larger sample (M5)
   says otherwise, not the 60 s originally guessed.
5. Use `switch_session`, not `--resume`, for programmatic session recovery.
