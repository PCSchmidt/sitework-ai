# M5 agent-slow-path eval — expanded (30-fixture) seeded incident results

`evaluation/agent_eval.py` output (docs/09 §3, docs/12 M5 items 2-3). 30 hand-designed incidents
(`evaluation/build_seed_incidents.py` -- grew from M3's 10 to 30, see that file's fixtures 11-30
for what's new), run for real through `agent.worker.AgentWorker.process_one()` against the real
`prime-agent` 0.9.3 CLI, one incident at a time -- not a mock, not a subset. Full machine-readable
output: `evaluation/eval-m5-report.json`.

## Result (2026-09-18)

| event_id | expected state | actual state | expected class | actual class | wall_s |
| --- | --- | --- | --- | --- | --- |
| evt_seed_evidence_inconsistent_01 | needs_review | needs_review | — (gate test) | normal_ops | 56.9 |
| evt_seed_evidence_inconsistent_02 | needs_review | needs_review | — (gate test) | normal_ops | 56.9 |
| evt_seed_minimal_window_01 | confirmed | confirmed | near_miss | near_miss | 55.3 |
| evt_seed_near_miss_01 | confirmed | confirmed | near_miss | near_miss | 71.6 |
| evt_seed_near_miss_approaching_stationary_01 | confirmed | confirmed | near_miss | near_miss | 80.1 |
| evt_seed_near_miss_boundary_close_01 | confirmed | confirmed | near_miss | near_miss | 54.2 |
| evt_seed_near_miss_boundary_far_01 | confirmed | confirmed | near_miss | near_miss | 60.0 |
| evt_seed_near_miss_long_dwell_01 | confirmed | confirmed | near_miss | near_miss | 68.8 |
| evt_seed_normal_ops_01 | confirmed | needs_review\* | normal_ops | — | 150.0 |
| evt_seed_normal_ops_boundary_01 | confirmed | confirmed | normal_ops | normal_ops | 38.9 |
| evt_seed_normal_ops_moving_apart_01 | confirmed | confirmed | normal_ops | normal_ops | 46.0 |
| evt_seed_proximity_minimal_violation_01 | confirmed | confirmed | violation | violation | 111.4 |
| evt_seed_proximity_multi_person_01 | confirmed | needs_review\* | violation | — | 150.0 |
| evt_seed_proximity_multi_vehicle_01 | confirmed | confirmed | near_miss | near_miss | 42.2 |
| evt_seed_speed_false_positive_01 | confirmed | confirmed | false_positive | false_positive | 76.7 |
| evt_seed_speed_false_positive_fluctuating_01 | confirmed | needs_review\* | false_positive | — | 150.0 |
| evt_seed_speed_violation_01 | confirmed | confirmed | violation | violation | 82.2 |
| evt_seed_speed_violation_accelerating_01 | confirmed | confirmed | violation | violation | 96.5 |
| evt_seed_speed_violation_edge_01 | confirmed | confirmed | violation | **near_miss** | 90.0 |
| evt_seed_speed_violation_severe_01 | confirmed | confirmed | violation | violation | 56.7 |
| evt_seed_ttc_closing_01 | confirmed | confirmed | near_miss | near_miss | 82.2 |
| evt_seed_violation_01 | confirmed | confirmed | violation | violation | 95.0 |
| evt_seed_violation_boundary_01 | confirmed | confirmed | violation | violation | 63.5 |
| evt_seed_violation_severe_01 | confirmed | confirmed | violation | violation | 50.5 |
| evt_seed_zone_false_positive_01 | confirmed | confirmed | false_positive | false_positive | 43.7 |
| evt_seed_zone_false_positive_brief_01 | confirmed | needs_review\* | false_positive | — | 150.0 |
| evt_seed_zone_false_positive_reentry_01 | confirmed | confirmed | false_positive | false_positive | 70.2 |
| evt_seed_zone_violation_01 | confirmed | confirmed | violation | violation | 40.4 |
| evt_seed_zone_violation_edge_01 | confirmed | confirmed | violation | violation | 53.0 |
| evt_seed_zone_violation_long_01 | confirmed | confirmed | violation | violation | 38.4 |

\* All 4 hit the then-configured 150s external supervisory timeout (`PrimeAgentTimeout`,
spike-01 Finding 4) — see "Timeout retest" below; none were a real agent-quality failure.

| Metric | Raw result | Target (docs/09 §3) |
| --- | --- | --- |
| Validation pass rate | 26/30 = **86.7%** (FAIL vs. raw target) | ≥ 90% |
| Classification agreement | 23/28 = **82.1%** (excludes the 2 gate-rejection fixtures by design) | ≥ 80% (met even on the raw, un-adjusted number) |
| p50 triage latency | **68.8 s** | ≤ 90 s (spike-01 Finding 6) |
| max triage latency | **150.0 s** (= the timeout ceiling itself, for the 4 that hit it) | ≤ 120 s (already over budget in M3 too, at 96.0s) |

**Raw validation pass rate (86.7%) misses the ≥90% target. Classification agreement (82.1%)
clears its target.** See below for why the validation-rate miss is a calibration finding, not an
agent-capability regression.

## Timeout retest — the real finding

All 4 validation failures were **identical in kind**: `PrimeAgentTimeout` at exactly 150.0s, not a
schema failure, not a Band-3 mismatch, not a wrong classification. Re-ran those exact 4 fixtures
with `--prompt-timeout-s 220`:

| event_id | wall_s (retest) | state | classification |
| --- | --- | --- | --- |
| evt_seed_normal_ops_01 | 65.3 | confirmed | normal_ops (correct) |
| evt_seed_proximity_multi_person_01 | 48.3 | confirmed | violation (correct) |
| evt_seed_speed_false_positive_fluctuating_01 | 63.5 | confirmed | false_positive (correct) |
| evt_seed_zone_false_positive_brief_01 | 48.1 | confirmed | false_positive (correct) |

**All 4 completed correctly in 48-65 seconds** -- nowhere near even the old 150s ceiling, let
alone the 220s retest allowance. This is real run-to-run latency variance (the same
`evt_seed_normal_ops_01` fixture passed at 87.9s in the M3 run against the same fixture, then hit
the 150s ceiling on this run's first attempt, then passed at 65.3s on retest -- three different
wall-clock times for the same deterministic input), not a fixture, prompt, or capability defect.

**Action taken, not just noted:** `agent/prime_adapter.py`'s `DEFAULT_TIMEOUT_S` raised from
150s → **210s** (~2x the highest max ever observed across M3+M5, 96.0s), propagated to
`evaluation/agent_eval.py`'s CLI default and `scripts/smoke_test.py`. This is the concrete
"threshold calibration pass" docs/12 M5 item 3 asks for, backed by a controlled retest rather than
a guess.

**Timeout-adjusted metrics** (substituting the retest's 4 correct outcomes for the original
timeout failures -- what this eval set would have scored with today's 210s default):

| Metric | Timeout-adjusted result |
| --- | --- |
| Validation pass rate | 30/30 = **100%** |
| Classification agreement | 27/28 = **96.4%** |

This is presented as a *secondary*, clearly-labeled number, not a replacement for the raw one --
the raw 86.7% is what actually happened on the first pass with the timeout this project shipped
with until today, and that's the number that matters for judging whether the *old* default was
well-calibrated (it wasn't, which is exactly the finding).

## A genuine classification disagreement (not a timeout)

`evt_seed_speed_violation_edge_01` (speeds 2.3-2.4 m/s, just over the 2.2 m/s dock limit every
frame) was labeled `violation` in `expected.json`, on the assumption that "consistently over the
limit" maps directly to violation. The agent returned `near_miss` instead, and completed cleanly
in 90s -- not a timeout, not a schema/gate failure. On inspection this is a **fixture-labeling
issue, not an agent error**: `agent/prompts/trajectory_inspector.md` §6's strict numeric
near_miss/violation cutoffs (`<2.0m` / `<1.0m`) only apply to *proximity*-kind incidents.
Zone/speed-kind incidents go through `agent/prompts/generic_classification.md` instead, whose
guidance is qualitative ("near_miss ... if it's a borderline case you'd want a human double
check") -- a speed reading just barely over the limit is a defensible "borderline" call under that
prompt, even though my fixture's `expected.json` assumed a hard numeric rule that doesn't actually
govern this rule kind. Left uncorrected in `expected.json` for this report (fixing the label after
seeing the model's answer would be moving the goalposts); noted here as a fixture-design lesson for
future speed/zone fixtures, not scored as an agent failure in the write-up above, though it is
counted as a disagreement in the raw 82.1%/96.4% classification-agreement numbers.

## What else is new vs. the M3 (n=10) report

- 20 new fixtures target the exact numeric boundaries `trajectory_inspector.md` uses (near_miss
  `<2.0m`, violation `<1.0m`) and multi-track distractor scenes (does the agent pick the claimed
  pair out via `event.json`'s `involved_track_ids`, not just whatever's closest?) -- both held up:
  every boundary fixture classified correctly, and both multi-track fixtures
  (`proximity_multi_vehicle_01`, `proximity_multi_person_01`) picked the right pair.
- More zone/speed `false_positive` coverage (3 new cases vs. 1 in M3) -- all 3 correct, confirming
  the agent's tracks.jsonl-reading judgment isn't limited to the one pattern M3 tested.
- `evaluation/agent_eval.py` now also aggregates `tokens_in`/`tokens_out` per incident from
  `IncidentRecord.agent_run` (closes a docs/09 §3 gap -- "not yet aggregated" until M4's DB wiring
  landed) -- added *after* this run started, so this report doesn't have token numbers for the
  full 30; a future `make agent-eval` run will.

## Honest caveats

- n=30 is still synthetic hand-built tracklet fixtures, not real camera footage -- same scope
  limit as M3 (validates the agent/Band-3/schema pipeline, not fast-path detection/tracking
  accuracy or real per-camera calibration, both tracked separately in `docs/12-roadmap.md`).
- The 150s→210s timeout change is backed by exactly one controlled retest of 4 fixtures, not a
  large-sample latency study -- a reasonable, evidence-based adjustment, not a definitively
  "correct" number. If a future eval run shows fixtures still timing out at 210s, that's real
  signal to look at prompt/turn-count tuning, not just raise the number again indefinitely.
- Token/incident aggregation exists in code now but has no real numbers in this report yet (see
  above) -- docs/09 §3's "Tokens/incident ≤ budget" row stays unfilled until the next full run.
