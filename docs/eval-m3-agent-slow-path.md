# M3 agent-slow-path eval — seeded incident results

`evaluation/agent_eval.py` output (docs/09 §3, docs/12 M3 exit criterion). Ten hand-designed
incidents (`evaluation/build_seed_incidents.py`, `evaluation/fixtures/incidents/`), run for real
through `agent.worker.AgentWorker.process_one()` against the real `prime-agent` 0.9.3 CLI — not a
mock. Full machine-readable output: `evaluation/fixtures/m3_eval_report.json`.

## Result (2026-09-17)

| event_id | expected state | actual state | expected class | actual class | wall_s |
| --- | --- | --- | --- | --- | --- |
| evt_seed_evidence_inconsistent_01 | needs_review | needs_review | — (gate test) | normal_ops | 96.0 |
| evt_seed_minimal_window_01 | confirmed | confirmed | near_miss | near_miss | 75.6 |
| evt_seed_near_miss_01 | confirmed | confirmed | near_miss | near_miss | 75.3 |
| evt_seed_normal_ops_01 | confirmed | confirmed | normal_ops | normal_ops | 87.9 |
| evt_seed_speed_false_positive_01 | confirmed | confirmed | false_positive | false_positive | 84.2 |
| evt_seed_speed_violation_01 | confirmed | confirmed | violation | violation | 93.2 |
| evt_seed_ttc_closing_01 | confirmed | confirmed | near_miss | near_miss | 74.9 |
| evt_seed_violation_01 | confirmed | confirmed | violation | violation | 61.1 |
| evt_seed_zone_false_positive_01 | confirmed | confirmed | false_positive | false_positive | 41.5 |
| evt_seed_zone_violation_01 | confirmed | confirmed | violation | violation | 57.9 |

| Metric | Result | Target (docs/09 §3) |
| --- | --- | --- |
| Validation pass rate | **10/10 = 100%** | ≥ 90% |
| Classification agreement | **9/9 = 100%** (excludes the 1 gate-rejection fixture by design) | ≥ 80% |
| p50 triage latency | **75.6 s** | ≤ 60 s (spike-01 already revised this to a realistic 90–120 s budget) |
| p95 / max triage latency | **96.0 s** | ≤ 120 s |

**M3 exit criterion (docs/12: "validation pass ≥ 90% on the seeded set") is met, cleanly.**

## What each result actually demonstrates

- **`evt_seed_evidence_inconsistent_01`** is the one fixture where `expected_state=needs_review`
  by design: the `TriggerEvent` deliberately claims `min_distance_m=1.0` while the accompanying
  `tracks.jsonl` never goes below 2.6 m (a simulated evidence-capture bug). Band-3
  (`agent/band3.py`) correctly rejected it regardless of what the agent said — this is the gate
  doing its job, not a model failure, which is why `check_classification: false` excludes it from
  the classification-agreement metric. The agent's own answer (`normal_ops`) was reasonable given
  the tracks it was actually handed; the point of the fixture is that the gate catches the
  fast-path/evidence mismatch either way.
- All 9 other fixtures — 6 proximity-kind, 2 zone-intrusion-kind, 2 speed-kind (one runs both a
  violation and a false_positive case) — passed Band-3 and matched the hand-labeled classification
  exactly, including the two "false_positive" fixtures where the deterministic trigger's own claim
  doesn't hold up against the tracked data (the agent correctly judged the claimed condition never
  actually occurred, not just echoed the fast path's label).
- `evt_seed_ttc_closing_01` (still-closing-at-last-frame case) produced a correct `ttc_s`-eligible
  verdict — not scored separately here since `ttc_s` isn't part of the Band-3 cross-check
  (docs/06 §3 only cross-checks distance/velocity), but confirms the field computes sensibly.

## Honest caveats

- n=10 is small; docs/09 §3's full eval set target is 30+ (M5). Treat this as "the mechanism works
  end-to-end, cleanly, on a deliberately varied first batch," not a statistically tight estimate —
  a single flash-tier model miss would have dropped validation pass to 90% exactly.
- All 10 incidents ran sequentially against one long-lived-per-incident `PrimeAdapter` process (one
  process per incident, matching the real `worker.py`/one-adapter-per-incident design) — this
  avoided the concurrent-RPC daemon contention spike-01 hit when multiple ad hoc invocations raced
  the same background daemon.
- p50 (75.6s) and max (96.0s) land inside spike-01's revised 90–120s budget note, not the original
  60s guess docs/prime-agent-feasibility.md §5 used before that finding.
- This is 10 synthetic (hand-built) tracklet fixtures, not real camera footage — it validates the
  agent/Band-3/schema pipeline, not the fast path's detection/tracking accuracy (that's
  `docs/benchmarks.md`'s job) or real-world calibration (still open, see docs/12 M2 notes on
  per-camera calibration).
