# SiteWatch AI — Master Project Plan

**Autonomous Industrial Safety & Fleet Telemetry Platform**
A hybrid deterministic/probabilistic computer vision system for warehouses and construction sites.

| Field | Value |
| --- | --- |
| Project | SiteWatch AI (`sitework-ai`) |
| Type | Portfolio / reference-architecture project (no live cloud deployment required) |
| Status | M0–M5 closed (see `docs/12-roadmap.md`); M6 (reference architecture & portfolio polish) in progress -- Terraform for all 3 clouds + iac-check + runbook review + cost model + simulated-live replay mode done, portfolio polish (README/ADR/diagrams) remaining |
| Source of idea | `project_concepts_ideas.md` (Gemini conversation, summarized in [docs/01-vision-and-scope.md](docs/01-vision-and-scope.md)) |
| Existing IaC artifact | `SiteWatch AI - AWS ECS Fargate & EFS Terraform Configuration.pdf` (full AWS Terraform spec) |

---

## 1. Executive Summary

SiteWatch AI is a full-stack, AI-enabled computer vision application that ingests streaming video from warehouse and construction site cameras, detects and tracks people and heavy machinery in real time, projects detections onto a metric ground plane, evaluates deterministic spatial safety rules (geofences, proximity envelopes, time-in-zone), and escalates only ambiguous or compound anomalies to a multi-agent LLM reasoning layer that performs kinematic verification, regulatory compliance correlation, and end-of-shift audit synthesis.

The defining architectural idea — and the portfolio centerpiece — is the **dual-plane split**:

- **Fast path (deterministic, 30–60 FPS):** quantized detectors (YOLO11 / RT-DETR on TensorRT), multi-object tracking (ByteTrack / BoT-SORT), Kalman state estimation, planar homography, and geometric geofencing (Shapely). Pure math. Zero LLM cost. Hard safety interlocks trip here.
- **Slow path (probabilistic, event-driven):** a containerized Prime Agent reasoning worker with
  sub-agent specialists (trajectory/collision inspector, compliance auditor, shift synthesizer) that consumes structured anomaly events — not raw frames — and produces explainable, auditable incident reports.

Cost discipline is a first-class requirement: the entire system develops and demos **locally at 
~$0** (MediaMTX-simulated RTSP feeds, Docker Compose, free/cheap open-weight LLMs such as
GLM-Flash class models via OpenRouter/Z.ai), and the cloud story is delivered as a **deployable reference architecture** — syntactically validated Terraform for AWS, GCP, and Azure plus enterprise-grade runbooks — without ever paying for always-on cloud GPU infrastructure.

## 2. Goals & Non-Goals

### Goals
1. **G1 — Working end-to-end local demo.** `docker compose up --build` runs simulated RTSP feeds
   through detection → tracking → geofencing → agent triage → dashboard in one command, fully offline.
2. **G2 — Hybrid architecture with hard contracts.** Deterministic perception/reasoning boundary enforced by versioned Pydantic schemas; LLM never in the life-safety critical path.
3. **G3 — Explainable safety intelligence.** Every incident carries machine-computed telemetry (metric distances, velocities, timelines) annotated with contextual narrative and severity.
4. **G4 — Near-zero cost operation.** Development and portfolio demo cost <$10 total (LLM spend);
   cloud demo uses the "simulated live" replay pattern (pre-computed telemetry replayed over WebSockets).
5. **G5 — Deployable reference architecture.** Valid Terraform for AWS/GCP/Azure, CI-validated with
   `terraform fmt -check` + `terraform validate`, plus three cloud runbooks and cost model.
6. **G6 — Honest, reproducible evaluation.** Published benchmark matrix (mAP, MOTA/IDF1, FPS, latency, VRAM) on public industrial datasets with a reproducible eval harness.

### Non-Goals
- No live production deployment, no real customer site integration, no actual E-stop hardware control.
- No training of detection models from scratch (fine-tuning of open weights only, if time allows).
- No 24/7 cloud video streaming (egress + GPU cost); cloud demo replays recorded telemetry.
- No multi-tenancy/SaaS features.

## 3. Success Criteria

| # | Criterion | Measured by |
| --- | --- | --- |
| S1 | Full stack runs offline with one command | Fresh-clone `docker compose up --build` smoke test passes |
| S2 | ≥ 3 concurrent streams at ≥ 25 FPS on the target GPU recorded in `docs/spikes/spike-00-gpu-benchmark.md` (fallback: 2 streams if the probe shows laptop-class hardware) | `evaluation/benchmark_models.py` output, published to `docs/benchmarks.md` (generated deliverable, produced at M5) |
| S3 | LLM invoked < 5 times per 10-min clip | Telemetry counters in event bus audit log |
| S4 | Every *persisted* agent output validates against schemas | 100% of incident records pass the schema + recomputation gate (failures route to `needs_review`, never the DB); first-try pass rate ≥ 90% is the tracked agent-quality metric (`docs/09-testing-and-evaluation.md`) |
| S5 | `terraform validate` green on 3 clouds | GitHub Actions workflow `iac-check.yaml` |
| S6 | Eval harness reproduces published numbers | `make eval` runs headless, seeded, CPU/GPU-portable |

## 4. Architecture at a Glance

```
[MediaMTX simulated RTSP / MP4 loop]  (or real cameras later)
        |
        v
+---------------------------------------------------------------+
| FAST PATH — Edge Vision Worker (GPU container)                |
|  YOLO11/RT-DETR (TensorRT) -> ByteTrack -> Kalman state       |
|  -> Planar homography (px -> meters) -> Shapely geofencing    |
+---------------------------------------------------------------+
        |  structured tracklet telemetry (JSON, ~10 Hz)
        v
+---------------------------------------------------------------+
| TELEMETRY BROKER + RULE ENGINE (Redis Streams; Kafka in prod) |
|  fast-path geofence/proximity evaluation, event dedup         |
+---------------------------------------------------------------+
        |  anomaly trigger events (rare, compound rules only)
        v
+---------------------------------------------------------------+
| SLOW PATH — Prime Agent Reasoning Worker (container)          |
|  supervisor daemon + headless IPython REPL + sub-agent pool   |
|  - Trajectory & Collision Inspector (scipy kinematics)        |
|  - Compliance Auditor (site rules, OSHA-style rationale)      |
|  - Shift Synthesizer (scheduled KPI digests)                  |
+---------------------------------------------------------------+
        |  incidents, reports, directives
        v
+---------------------------------------------------------------+
| DELIVERY PLANE                                                |
|  FastAPI (REST + WebSockets) | PostgreSQL | Incident clips    |
|  React/Vite dashboard: live bounding boxes + 2D site map      |
+---------------------------------------------------------------+
```

Details: [docs/02-system-architecture.md](docs/02-system-architecture.md).
Design rationale: [docs/03-hybrid-design.md](docs/03-hybrid-design.md) and ADRs in [docs/adr/](docs/adr/).
The slow path's runtime is an **embedded Prime Agent** — feasibility analysis with verified
integration surfaces: [docs/prime-agent-feasibility.md](docs/prime-agent-feasibility.md).

## 5. Roadmap (Milestones)

Effort estimates assume evenings/weekends pace (~10–15 h/week).

| Milestone | Deliverable | Est. effort | Acceptance |
| --- | --- | --- | --- |
| **M0 — Scaffolding** ✅ CLOSED | Repo layout, Docker Compose skeleton, CI (lint, tests, `terraform validate`), config schema (`cameras.yaml`, `zones.yaml`) | 1 week | CI green on empty pipeline; `make up` starts broker + API + UI |
| **M1 — Perception core** ✅ CLOSED | Ingestion (MP4 loop + MediaMTX), detector wrapper (**YOLO11s** per spike-00; forklift via truck/bus proxy per spike-02), ByteTrack tracker, JSON tracklet publisher, benchmark harness v1 | 2–3 weeks | S2 partially met (1 stream ≥ 25 FPS); eval numbers reproducible |
| **M2 — Spatial layer** ✅ CLOSED | Camera calibration + homography, ground-plane projection, zone polygon engine (Shapely), fast-path rule engine (proximity, dwell, speed), telemetry broker (PPE rules arrive at M5 with fine-tuned classes) | 2 weeks | Deterministic demo: forklift-vs-worker proximity event fires on sample clip with metric distances |
| **M3 — Agent slow path** ✅ CLOSED | **M3.0 feasibility spike first** (`docs/prime-agent-feasibility.md` §5 → ADR-005), then embedded Prime Agent via RPC adapter (`agent/prime_adapter.py`, pinned version, contract test); sub-agent specs (trajectory inspector, compliance auditor); Pydantic-verified outputs + recomputation gate; incident DB writes | 2–3 weeks | Spike pass criteria met; S3 met end-to-end: anomaly → agent incident report with verified kinematics; first-try validation ≥ 90% — **met: 10/10 on the seeded set, `docs/eval-m3-agent-slow-path.md`.** Incident DB writes deferred to M4 (storage-layer follow-up, not an agent-pipeline gap) |
| **M4 — Delivery plane** ✅ CLOSED | FastAPI REST + WebSocket stream, React dashboard (incident feed, needs_review queue, evidence viewer, KPI bar), clip persistence + evidence endpoints, shift report rendering | 2 weeks | Live dashboard plays a real incident end to end -- **met**: verified against the real docker-compose stack, including the WS push through the exact proxy path the browser uses. Video+boxes overlay/2D site canvas deferred (needs `frame.ticker`, still unwired) |
| **M5 — Evaluation & tuning** ✅ CLOSED | Full benchmark matrix (2 models × 2 precisions × 1-3 streams), MOTA/IDF1 on MOT17, expanded eval set (10→30), threshold calibration, `docs/benchmarks.md` | 1–2 weeks | **S2 and S6 met.** S2 confirmed via an idle-recovered-GPU rerun (3-stream FP16 TensorRT: 30.2 FPS min-stream); the sustained-load floor (9.5-13.2 FPS/stream) is published alongside it for honest production sizing. S6 met for the deterministic (benchmark/tracking) harnesses; `make agent-eval` stays CLI-availability-gated (prime-agent's pre-existing private-registry gap) |
| **M6 — Reference architecture** (in progress) | Terraform for AWS (from existing PDF spec), GCP, Azure; `iac-check` CI; three cloud runbooks; cost model; ADRs finalized; simulated-live replay mode for public demo | 2 weeks | S5 met; public portfolio demo costs $0/mo -- **S5 met**: all 3 environments' Terraform realized and `fmt`/`validate` green (verified locally and via `iac-check` CI); runbook review + cost model finalize done; simulated-live replay mode done (`scripts/replay_demo.py`, `make replay-up`, real bugs found and fixed by actually running the stack -- docs/12 M6). Remaining: README/ADR/diagram polish |

Full milestone detail with task breakdowns: [docs/12-roadmap.md](docs/12-roadmap.md).

## 6. Document Index

| Document | Contents |
| --- | --- |
| [docs/01-vision-and-scope.md](docs/01-vision-and-scope.md) | Problem, idea provenance, personas, scope, success criteria |
| [docs/02-system-architecture.md](docs/02-system-architecture.md) | Components, data flow, latency budget, tech stack, failure modes |
| [docs/03-hybrid-design.md](docs/03-hybrid-design.md) | Deterministic/probabilistic split, contracts, gating, verification gates |
| [docs/04-data-and-models.md](docs/04-data-and-models.md) | Datasets, model selection, quantization, calibration, benchmark matrix |
| [docs/05-agent-orchestration.md](docs/05-agent-orchestration.md) | Agent roles, sub-agent specs, model routing, token guards, scheduling |
| [docs/prime-agent-feasibility.md](docs/prime-agent-feasibility.md) | **Feasibility of Prime Agent as an embedded application component** (verified RPC/print modes, budget flags, risks, de-risk spike) |
| [docs/06-schemas-and-api.md](docs/06-schemas-and-api.md) | Event/tracklet/incident JSON schemas, Pydantic models, REST/WS API, DB schema |
| [docs/07-repo-layout.md](docs/07-repo-layout.md) | Final repository tree, conventions, CI pipelines |
| [docs/08-security.md](docs/08-security.md) | Threat model, sandboxing, IAM boundaries, secrets, data privacy |
| [docs/09-testing-and-evaluation.md](docs/09-testing-and-evaluation.md) | Test pyramid, eval harness, metrics, replay testing |
| [docs/10-cost-model.md](docs/10-cost-model.md) | Local dev cost, LLM spend model, cloud BOM (idle vs production), guardrails |
| [docs/11-risks.md](docs/11-risks.md) | Risk register with mitigations |
| [docs/12-roadmap.md](docs/12-roadmap.md) | Detailed milestone task breakdowns |
| [docs/deployment/aws-deployment-guide.md](docs/deployment/aws-deployment-guide.md) | ECS Fargate + SQS + EFS runbook (aligned with existing Terraform PDF) |
| [docs/deployment/gcp-deployment-guide.md](docs/deployment/gcp-deployment-guide.md) | Cloud Run + Pub/Sub + Filestore runbook |
| [docs/deployment/azure-deployment-guide.md](docs/deployment/azure-deployment-guide.md) | Container Apps + Service Bus + Azure Files runbook |
| [docs/adr/ADR-001-fast-slow-path-separation.md](docs/adr/ADR-001-fast-slow-path-separation.md) | Why edge inference and agent reasoning are separate planes |
| [docs/adr/ADR-002-message-broker-selection.md](docs/adr/ADR-002-message-broker-selection.md) | Redis Streams locally, Kafka/SQS/Pub-Sub/Service Bus in cloud |
| [docs/adr/ADR-003-model-selection-and-routing.md](docs/adr/ADR-003-model-selection-and-routing.md) | Vision model and LLM tiering strategy |
| [docs/adr/ADR-004-documentation-only-cloud-deployment.md](docs/adr/ADR-004-documentation-only-cloud-deployment.md) | Why cloud delivery is IaC + runbooks, not live infra |
| [docs/adr/ADR-005-prime-agent-as-embedded-component.md](docs/adr/ADR-005-prime-agent-as-embedded-component.md) | Embedding Prime Agent as the cognitive plane runtime, with fallback |

## 7. Top Risks (summary)

1. **Scope explosion** — the full stack is large. Mitigation: milestone gating; M1–M3 are the minimum viable portfolio story; each milestone stands alone.
2. **Dataset licensing/availability drift** — public datasets move or restrict access. This fired
   during M1-prep (see [docs/11-risks.md](docs/11-risks.md) R2); resolved by pinning a verified set
   (Mendeley CC BY 4.0 machinery frames, HF warehouse stills, MOT17 mirror, Pexels demo clips) with
   manifests + hashes in `data/manifests/`.
3. **LLM nondeterminism corrupting operational data** — mitigation: schema-verified outputs,
   retry/escalation policy, agent outputs never auto-execute safety actions.
4. **Cost leak from autonomous agents** — mitigation: hard turn/token/time caps, trigger-rate budget alarms, tiered model routing.
5. **Homography accuracy on real footage** — mitigation: manual calibration tooling + documented error bounds; treat metric distances as estimates with confidence intervals.
6. **Prime Agent interface drift** — mitigation: pinned version, single adapter module, golden RPC contract test in CI; LiteLLM fallback worker behind identical contracts (ADR-005).

Full register: [docs/11-risks.md](docs/11-risks.md). Prime Agent embedding feasibility:
[docs/prime-agent-feasibility.md](docs/prime-agent-feasibility.md).

## 8. Immediate Next Actions

M0's original bootstrap checklist (repo skeleton, dataset licensing, first detector/tracker wire-up)
is long done -- superseded here rather than left stale; see `docs/12-roadmap.md` for the full
milestone-by-milestone history. Current, as of M6 in progress (2026-09-19):

1. README narrative pass, ADR finalization, demo GIF/video, architecture diagrams (C4 + sequence).
2. Optional stretch, not part of M6 exit: stream watchdog + parameter-reviewer sub-agents
   (docs/05 §1, marked optional since M0.5); a genuine cold-boot (not idle-recovered) rerun of the
   M5 multi-stream benchmark matrix for an even cleaner S2 best-case number.
