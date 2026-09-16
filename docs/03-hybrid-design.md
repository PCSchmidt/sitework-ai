# 03 — Hybrid Deterministic/Probabilistic Design

This is the architectural thesis of SiteWatch AI: pure probabilistic systems (end-to-end VLM
reasoning on frames) are too slow, costly, and non-deterministic for physical safety; pure
deterministic systems (handcrafted OpenCV heuristics) fail on edge cases, occlusion, and context.
The answer is a **neuro-symbolic dual-plane architecture** with explicit contracts.

## 1. The Three Bands

```
+---------------------------------------------------------------+
| BAND 1: DETERMINISTIC PERCEPTION & KINEMATICS  (30-60 Hz)     |
|  detectors, tracking, Kalman, homography, geometric rules     |
+---------------------------------------------------------------+
                          | structured telemetry, boundary violations
                          v
+---------------------------------------------------------------+
| BAND 2: PROBABILISTIC REASONING & SYNTHESIS    (event-driven) |
|  intent/context, near-miss causality, compliance narrative,   |
|  parameter adaptation proposals                               |
+---------------------------------------------------------------+
                          | structured directives (validated)
                          v
+---------------------------------------------------------------+
| BAND 3: DETERMINISTIC CONTROL & AUDIT GATES                    |
|  alarm dispatch, DB transactions (ACID), report publication   |
+---------------------------------------------------------------+
```

**Rule:** an LLM is never in the direct path of a life-safety command or a database write.
Band 3 executes only validated, deterministic actions.

## 2. What Each Band Owns

### Band 1 — Deterministic (never probabilistic)
- Tracklet state: Hungarian data association (ByteTrack), Kalman filtering for position/velocity.
- Geometric invariants: zone membership is set intersection (Shapely), not a guess:
  `worker_ground_point ∈ swing_radius_polygon` — boolean, exact given calibration.
- Proximity: minimum metric distance from homography-projected ground points.
- Dwell: timestamp arithmetic on zone membership intervals.
- Hard alarms: rule engine fires buzzer/SMS/push simulation **immediately** on violation.

### Band 2 — Probabilistic (LLM, gated)
- **Context & intent:** worker next to a tagged-out, idle excavator during lunch ≠ worker walking
  behind a reversing forklift at 10 km/h. Band 1 sees identical geometry; Band 2 distinguishes them
  using equipment state, shift schedule, and time.
- **Near-miss causality:** trajectory grazed the threshold — was the worker retreating or oblivious?
  Did the vehicle brake? Agent inspects the temporal tracklet window and reasons about intent.
- **Regulatory synthesis:** mapping verified telemetry to OSHA-style narrative and severity.
- **Parameter adaptation (proposal-only):** "expand buffer radius 1.5× during rain/shift change" —
  emitted as a *directive proposal*, applied only after deterministic validation and a human or
  policy approval flag.

### Band 3 — Deterministic gates on agent output
- Pydantic schema validation + range checks + enum severity clamps.
- Cross-checks: agent-claimed min-distance must match recomputed value from the stored tracklet
  window (replay through the same deterministic functions). Mismatch > tolerance ⇒ reject + log.
- Idempotent, transactional DB writes; append-only audit log.

## 3. Integration Patterns

| Pattern | Deterministic element | Probabilistic element | Why it works |
| --- | --- | --- | --- |
| **Gated invocation** | Geometric thresholds produce TriggerEvents | Sub-agents spawn only on anomalies | LLM cost ∝ incident count, not frame count (< 5 calls per 10-min clip) |
| **Sandboxed code verification** | Agent executes Python in IPython REPL against stored telemetry | Agent *hypothesizes* (e.g., "collision course"), *verifies* by running trajectory regression | Conclusions backed by executed deterministic code |
| **Verification gate** | Pydantic + recomputation cross-check | Agent generates narrative/severity | Hallucinated numbers cannot reach the DB |
| **Confidence forwarding** | Detector confidence, Kalman covariance, homography error estimate travel with telemetry | Agent weighs evidence quality in narrative | Explainability of uncertainty |

## 4. Failure Domain Isolation

- **LLM outage:** Band 1 alarms keep working at ≤ 500 ms. Triggers buffer. No safety regression.
- **Hallucination attempt:** verification gate rejects; incident goes to `needs_review` state with
  the raw telemetry retained; audit log records the rejection.
- **Latency spike:** agent work is async by construction; the alert path never waits.
- **Bad calibration:** homography error estimate is part of telemetry; rules can require a minimum
  calibration quality before firing metric-distance rules.

## 5. Determinism Where It Counts, Probabilism Where It Pays

| Question | Answered by |
| --- | --- |
| Is a person in the exclusion zone? | Band 1 (exact geometry) |
| How fast are they closing? | Band 1 (Kalman + homography) |
| Should the alarm sound *now*? | Band 1 (rule engine), zero LLM |
| Was this a near-miss or normal operations? | Band 2 (context) |
| What happened, why, and what should change? | Band 2 (narrative + proposals) |
| Is the record trustworthy? | Band 3 (recomputation + schema gates) |

## 6. What This Demonstrates (portfolio value)

1. Failure-domain isolation under an unreliable AI dependency.
2. Explainability suitable for regulator-facing narratives (math telemetry + contextual rationale).
3. Hardware/cost efficiency: sub-millisecond deterministic code at 30–60 Hz; LLM only on rare events.
4. Agent discipline: RLM sub-agents that compute rather than assert (REPL execution of kinematics).
