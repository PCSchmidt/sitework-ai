# 09 — Testing & Evaluation Strategy

## 1. Test Pyramid

| Level | What | Tooling |
| --- | --- | --- |
| Unit | schemas, geometry (homography known-answer tests), rule engine (synthetic tracklets), adapter serialization | pytest, fast, no GPU |
| Integration | compose stack with synthetic feeds: detector on fixture image → tracklet → trigger → agent stub → API | docker compose + pytest |
| Contract | golden RPC session vs pinned prime-agent; schema compat between TS/Py | CI `contract-agent.yaml` |
| E2E replay | recorded tracklet fixtures replayed over WS; snapshot dashboard states | **not built** -- `ui`'s `npm test` is `vitest run --passWithNoTests` (zero vitest tests exist); the closest real thing is `scripts/replay_demo.py` (M6), which replays fixtures into the real API/DB/WS path for a live demo, not as an automated dashboard-snapshot test |
| Benchmark | FPS/latency/VRAM matrix, MOTA/IDF1 | `evaluation/`, manual dispatch, GPU |

## 2. Known-Answer Tests (determinism proofs)

- Homography: synthetic ground plane with known 3D points → projected px → reprojected meters
  within tolerance; rotation/translation cases.
- Rule engine: hand-built track sequences that must/must-not fire each rule family, including
  dwell timing edges, cooldown dedup, calibration-quality gating (RMS just above/below the 2.0 px gate).
- Band-3 gate: mutated agent outputs must be handled per the tolerances in
  `06-schemas-and-api.md` §3 — a 0.05 m distance mutation **passes** (inside 0.15 m tolerance),
  a 0.5 m mutation is **rejected**, invalid severity enum is **rejected**.

## 3. Agent Evaluation (the probabilistic layer)

Because agent outputs are validated deterministically, evaluation reduces to measuring the gate:

| Metric | Definition | Target | M3 (n=10, 2026-09-17) | M5 (n=30, 2026-09-18) |
| --- | --- | --- | --- | --- |
| Validation pass rate | agent results passing schema+recompute first try | ≥ 90% | 10/10 = 100% | **26/30 = 86.7% raw** (FAIL); all 4 misses were the same then-150s external timeout, not a capability failure -- 30/30 = 100% on retest with the calibrated 210s timeout (docs/eval-m5-agent-slow-path.md) |
| Escalation rate | incidents needing tier-3 model | ≤ 15% | not yet wired (no tier escalation in M3's `worker.py`, see docs/05 §3's implementation note) | still not wired -- unchanged from M3 |
| Tokens/incident | mean + p95 from `agent_runs` | ≤ budget (docs/10-cost-model.md) | not yet aggregated (`agent_runs` table lands with M4's DB wiring) | aggregation now implemented in `evaluation/agent_eval.py` (reads `IncidentRecord.agent_run`), but added after this run started -- no real numbers yet, next `make agent-eval` run will have them |
| Triage latency | p50/p95 wall clock | ≤ 90 s / ≤ 120 s (revised from an initial 60 s guess by spike-01 Finding 6) | p50 75.6 s / max 96.0 s | p50 68.8 s / max 150.0 s (= the old timeout ceiling itself); real observed completions once retried topped out at 65.3s -- see M5 doc for why max looks worse without actually being worse |
| Classification agreement | agent verdict vs labeled ground truth on the seeded incidents | ≥ 80% | 9/9 = 100% | **23/28 = 82.1% raw** (meets target); 27/28 = 96.4% timeout-adjusted. One genuine disagreement traced to a fixture-labeling issue, not an agent error (docs/eval-m5-agent-slow-path.md) |

**M5 finding acted on:** `agent/prime_adapter.py`'s `DEFAULT_TIMEOUT_S` raised 150s → 210s, backed
by a controlled retest (the 4 timeout failures all completed correctly in 48-65s once given more
headroom) rather than a guess -- this is the M5 "threshold calibration pass" (docs/12-roadmap.md).

Eval set: 10 hand-designed incidents for M3, expanded to 30 at M5 (`evaluation/build_seed_incidents.py`
fixtures 11-30 add boundary-value proximity cases at the classifier's exact numeric cutoffs,
multi-track distractor scenes, and more zone/speed false_positive coverage), stored in
`evaluation/fixtures/incidents/` — synthetic tracklet fixtures exercising all three rule kinds and
both confirm/reject paths, not clips replayed through the real fast path (that integration lands
with the demo clips once real per-camera calibration exists, docs/12 M2 notes). Run via
`make agent-eval` (`evaluation/agent_eval.py`) against the real `prime-agent` CLI. Full result
tables and honest caveats: `docs/eval-m3-agent-slow-path.md` (n=10) and
`docs/eval-m5-agent-slow-path.md` (n=30, current).

## 4. Tracking Metrics

MOTA/IDF1/IDF1-vs-matches on MOT17 clips (via the pinned HF mirror) via
`evaluation/eval_tracking.py` using motmetrics; results land in `docs/benchmarks.md`. Note: the
mirror ships one `gt.txt` per base train sequence — resolve GT per base scene, not per detector
folder.

## 5. Reproducibility Rules

- Pinned weights + seeds + dataset manifests (SHA256) → every number in `docs/benchmarks.md`
  regenerable with `make eval`.
- Fixture-based CI runs CPU-only (no GPU in CI): use exported ONNX + CPU EP for a smoke path.

## 6. Demo Smoke Test

`scripts/smoke_test.py`: inject a synthetic TriggerEvent into the broker → assert incident row
created → assert WS message observed → print PASS. Runs in CI integration job with agent stubbed,
and locally against the real stack.
