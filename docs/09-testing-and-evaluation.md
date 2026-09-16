# 09 — Testing & Evaluation Strategy

## 1. Test Pyramid

| Level | What | Tooling |
| --- | --- | --- |
| Unit | schemas, geometry (homography known-answer tests), rule engine (synthetic tracklets), adapter serialization | pytest, fast, no GPU |
| Integration | compose stack with synthetic feeds: detector on fixture image → tracklet → trigger → agent stub → API | docker compose + pytest |
| Contract | golden RPC session vs pinned prime-agent; schema compat between TS/Py | CI `contract-agent.yaml` |
| E2E replay | recorded tracklet fixtures replayed over WS; snapshot dashboard states | pytest + vitest |
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

| Metric | Definition | Target |
| --- | --- | --- |
| Validation pass rate | agent results passing schema+recompute first try | ≥ 90% |
| Escalation rate | incidents needing tier-3 model | ≤ 15% |
| Tokens/incident | mean + p95 from `agent_runs` | ≤ budget (docs/10-cost-model.md) |
| Triage latency | p50/p95 wall clock | ≤ 60 s / ≤ 120 s |
| Classification agreement | agent verdict vs labeled ground truth on ~30 seeded incidents | ≥ 80% |

Eval set: 30 seeded incidents from the demo clips with hand labels (`normal_ops` / `near_miss` /
`violation` / `false_positive`), stored in `evaluation/fixtures/incidents/`.

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
