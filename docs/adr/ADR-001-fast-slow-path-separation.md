# ADR-001: Separate Edge Inference from Agent Reasoning Planes

**Status:** Accepted · **Date:** planning phase

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
