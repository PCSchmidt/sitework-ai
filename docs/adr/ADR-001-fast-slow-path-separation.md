# ADR-001: Separate Edge Inference from Agent Reasoning Planes

**Status:** Accepted and implemented · **Date:** 2026-09-16 (decided pre-M1); built out M1–M4

## Context
Raw frames must not flow into LLM reasoning: 30–60 FPS streams x N cameras would be prohibitively
expensive and slow, and LLM loops (seconds) cannot sit in a life-safety alert path. Conversely,
bounding boxes alone cannot answer intent/context questions ("is this a near-miss?").

## Decision
Two planes with a schema-enforced boundary:
- Fast path: detection, tracking, homography, geometric rules — deterministic, <= 500 ms alert path.
- Slow path: Prime Agent reasoning, triggered only by compound-rule TriggerEvents; consumes
  structured telemetry files, never frames; outputs schema-validated incidents.

## Consequences
+ Failure-domain isolation; cost proportional to incidents not frames; explainable evidence chains.
- Extra moving parts (broker, queue, worker); telemetry schema versioning discipline required.

## Alternatives considered
- Single monolith with inline LLM calls — rejected: latency, cost, nondeterminism in safety path.
- Pure deterministic (course-repo style) — rejected: no context/intent, brittle thresholds.

## Implementation note (M1–M4)

The boundary held in practice: `pipelines/vision/pipeline.py` never imports anything from
`agent/`, and `agent/worker.py` never touches raw frames -- only `TriggerEvent` + the evidence
window (`tracks.jsonl`/`clip.mp4`) cross the boundary, both schema-validated
(`pipelines/schemas/models.py`). The Band-3 gate (`agent/band3.py`) added at M3 is a direct
consequence of this ADR's "explainable evidence chains" claim: it's what makes the agent's
output checkable against the same raw data the fast path used, not just internally consistent.
