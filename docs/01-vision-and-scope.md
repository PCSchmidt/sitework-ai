# 01 — Vision & Scope

## 1. Problem Statement

Industrial environments — loading docks, warehouses, active construction sites — mix fast heavy machinery with vulnerable humans. Safety programs today rely on human spot-checks, static signage, and after-the-fact incident review. Continuous, automated, *explainable* safety telemetry is the gap SiteWatch AI addresses:

1. **Detect** people, forklifts, excavators, and PPE state in real time from standard CCTV/RTSP feeds.
2. **Quantify** risk in physical units — metric distances, velocities, time-in-zone — not just pixels.
3. **Decide** deterministically when a hard spatial rule is violated (no AI opinion required).
4. **Understand** ambiguous situations with an LLM agent layer that correlates context (shift state,
   equipment status, operational rules) and produces audit-grade incident narratives.
5. **Report** — end-of-shift compliance KPIs, near-miss trends, and exportable incident audits.

## 2. Idea Provenance

The concept emerged from a Gemini conversation (archived verbatim in
`project_concepts_ideas.md`) that progressed through these decisions:

| Decision point | Outcome |
| --- | --- |
| How to structure multi-agent development & runtime | Hierarchical research squad during development; four runtime agent roles (ingestion/calibration, perception/tracking filter, spatial/safety reasoning, operations/audit dispatch) |
| LLM placement | Downstream of vision: structured telemetry in, never raw frames; slow path only |
| Cloud hosting of the agent | Containerized Prime Agent as an event-driven microservice (ECS Fargate / Cloud Run / Container Apps) with persistent harness state on shared NFS-class storage |
| Relationship to JHU course repo | Separate standalone app; course repo stays deterministic, portfolio app is the hybrid probabilistic+deterministic system |
| Data sources | Verified public sources: Mendeley construction-machinery frames (CC BY 4.0), NVIDIA PhysicalAI Warehouse stills (CC-BY-4.0), Pexels demo clips, MOT17 tracking baseline, Pictor-v3 PPE |
| Cost posture | Local-first $0 development; serverless/free-tier demo hosting; "simulated live" telemetry replay instead of cloud video streaming |
| Model economics | Ultra-cheap/free open-weight LLMs (GLM-Flash class) for high-volume agent work; frontier models reserved for final synthesis |
| Cloud deployment | Documentation and validated IaC only — no live cloud spend |

## 3. Product Vision

> A hiring manager clones the repo, runs one command, and watches a simulated construction site where a tracked excavator and an unhelmeted worker converge; the deterministic layer computes the closing distance in meters and fires a trigger; the agent layer verifies the trajectory, writes a compliance-grade incident record; the dashboard shows it all live and exports the end-of-shift audit — at zero marginal cost.

## 4. Personas

| Persona | Need | How SiteWatch serves them |
| --- | --- | --- |
| **Portfolio reviewer (engineering lead)** | Judge systems design, CV depth, agent architecture maturity | Clean architecture docs, ADRs, benchmark matrix, validated IaC, one-command demo |
| **Site safety manager (fictional user)** | Fewer false alarms, auditable incidents, shift reports | Deterministic gating (low false positives), evidence-linked reports, KPI dashboards |
| **Integrator / MLOps engineer** | Deploy on their cloud without re-architecture | Cloud-agnostic mapping, Terraform modules, runbooks, cost model |

## 5. Scope

### In scope
- Multi-stream video ingestion from RTSP or looped MP4 (local, simulated feeds).
- Detection + tracking of persons, forklifts, excavators, loaders, trucks, and PPE classes.
- Planar homography calibration (pixel → ground plane meters) with a manual calibration tool.
- Zone geofencing (polygons) and proximity envelopes with time/distance compound rules.
- Anomaly event bus + containerized LLM agent reasoning layer (Prime Agent, RLM sub-agents).
- Incident persistence, REST/WebSocket API, React dashboard with 2D site map.
- End-of-shift report generation (Markdown/PDF) by scheduled agent worker.
- Multi-cloud deployable reference architecture (AWS/GCP/Azure Terraform + runbooks).
- Public benchmark harness with published metrics.

### Out of scope
- Live production deployment, customer integration, real interlock hardware (E-stop actuation is documented as a deterministic hook, never implemented against real equipment).
- Model training from scratch; multi-tenancy; mobile apps; audio analytics; drone imagery.
- 24/7 cloud GPU operation; cloud video egress at scale.

## 6. Demo Data Strategy

Primary: verified public datasets (see `04-data-and-models.md` §1 — validated hands-on during
M1-prep).
Demo clips: 3 Pexels clips mapped 1:1 to the demo cameras (`data/manifests/pexels-demo-clips.yaml`),
pinned in `assets/clips/` (git-ignored) so the demo never breaks when upstream sources change.

## 7. Constraints

| Constraint | Implication |
| --- | --- |
| Single developer, ~10–15 h/week | Milestones must each be shippable; ruthless scope control |
| Local GPU only (workstation or laptop-class; measured by spike-00 before S2 is committed) | Quantized INT8/FP16 models; no cloud GPUs |
| LLM budget ≤ $10 total dev, ≤ $2/mo demo | Tiered model routing + trigger-rate gating (see `10-cost-model.md`) |
| No live cloud infra | Everything cloud is IaC-validated + documented, not provisioned |
| Privacy (faces, plates, workers) | Portfolio demo uses public research datasets per license; blurring option documented (see `08-security.md`) |

## 8. Success Criteria

See `PLAN.md` §3 (S1–S6). These are the only definitions of "done" for the project.
