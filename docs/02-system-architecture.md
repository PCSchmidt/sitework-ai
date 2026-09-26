# 02 — System Architecture

## 1. Overview

SiteWatch AI is a set of cooperating containers organized in four planes. Video never crosses the fast/slow boundary; only structured telemetry does.

```
                       +--------------------------------+
                       |  INGESTION PLANE               |
                       |  MediaMTX RTSP server          |
                       |  (loops sample MP4s as feeds)  |
                       |  OR real RTSP cameras          |
                       +---------------+----------------+
                                       | RTSP
                                       v
+--------------------------------------------------------------------------+
| FAST PATH — PERCEPTION PLANE (pipeline/vision, GPU container)             |
|                                                                          |
|  FrameSource -> Decoder (GStreamer/PyAV, batched)                        |
|      -> Detector (YOLO11s, TensorRT FP16; INT8/RT-DETR not built)        |
|      -> Tracker (ByteTrack; BoT-SORT optional)                           |
|      -> State Estimator (per-track Kalman: position, velocity)           |
|      -> Geometry (homography px->meters; velocity in m/s)                |
|      -> Fast Rule Evaluator (Shapely: zone membership, proximity, dwell) |
|                                                                          |
|  Output: TrackletFrame messages @ ~10 Hz per camera (downsampled)        |
|  Output: TriggerEvents (compound rule violations, deduplicated)          |
+------------------------------------+-------------------------------------+
                                     | JSON (msgspec/protobuf-capable)
                                     v
+--------------------------------------------------------------------------+
| BROKER PLANE (infra/telemetry)                                            |
|  Redis Streams (local) | Kafka / SQS / PubSub / ServiceBus (cloud maps)   |
|  - stream: tracklets:{camera_id}  (5 min retention, XTRIM MINID)          |
|  - stream: trigger_events         (1 h retention, XTRIM MINID)            |
|  - consumer groups (XREADGROUP/XACK) for reliable downstream consumers    |
+----------------------+-------------------------------+-------------------+
                       | trigger events (rare)         | telemetry queries
                       v                               v
+--------------------------------------+   +---------------------------+
| SLOW PATH — COGNITIVE PLANE          |   | DELIVERY PLANE            |
| (agent/, Prime Agent container)      |   | (api/, ui/)               |
|                                      |   |                           |
|  Queue consumer / dispatcher         |   |  FastAPI backend          |
|    -> Trajectory & Collision         |   |   - REST: incidents, KPIs |
|       Inspector sub-agent            |<--|   - WS: live telemetry    |
|    -> Compliance Auditor sub-agent   |   |   - WS: incidents         |
|    -> (escalation: frontier model)   |   |  PostgreSQL: incidents,   |
|  Shift Synthesizer (scheduled)       |   |    tracks, shift KPIs     |
|  Persistent harness state:           |   |  Incident clip writer     |
|    /home/node/.prime on NFS-class volume  |   |   (S3/GCS/Blob or local)  |
+--------------------------------------+   |  React/Vite dashboard:    |
                                            |   - video + boxes overlay |
                                            |   - 2D site canvas        |
                                            |   - incident feed         |
                                            +---------------------------+
```

**Implementation status vs. this design (as of M6, 2026-09-19):** everything above is built and
verified except two pieces, both deliberately deferred rather than silently dropped. **Shift
Synthesizer** (a scheduled sub-agent doing cross-incident KPI synthesis) was never built; M4
shipped `api/reports.py` instead -- a pure-function HTML renderer that stitches together each
incident's own already-agent-written `narrative_md`, not a new scheduled agent invocation (see
docs/05 §1's note). **Video + boxes overlay / 2D site canvas** need `frame.ticker` (live track
positions pushed over WS), which stays unwired -- the dashboard's live incident feed, needs_review
queue, and evidence viewer (clip playback + tracks.jsonl) are real and verified, but there is no
live video/canvas view yet.

**Third gap, found and fixed 2026-09-18 while drawing `docs/13-architecture-diagrams.md`'s
container diagram, not disclosed until now because it wasn't known until then:** the vision-to-agent
evidence handoff (`pipelines/vision/evidence.py` → `agent/worker.py`'s `--evidence-root`) had never
actually been wired for real multi-container operation -- `docker-compose.yml`'s vision-\* services
didn't mount the `agent_workspace` volume, and `pipeline.py` had no `--evidence-root` flag,
so `EvidenceCapture()` silently wrote to an unshared directory inside each vision container. The M4
smoke test never caught this because it injects a `TriggerEvent` directly into Redis, bypassing
vision's evidence-writing step. Fixed for real (both the code and the compose wiring); see
docs/12-roadmap.md's M6 entry for the full account.

## 2. Component Responsibilities

| Component | Container | Key tech | owns |
| --- | --- | --- | --- |
| Ingestion simulator | `mediamtx` | RTSP server | Looping MP4 → RTSP feeds; camera config |
| Vision worker | `vision` | Python, GStreamer/PyAV, Ultralytics/ONNX, TensorRT, ByteTrack | Frames → tracklets → triggers; calibration |
| Telemetry broker | `redis` | Redis Streams | Messaging backbone, ring buffers |
| API backend | `api` | FastAPI, uvicorn, asyncpg | REST/WS, incident persistence, auth-lite |
| Agent worker | `agent` | Prime Agent (Node supervisor + IPython REPL), RLM sub-agents | Incident triage, compliance, reports |
| Database | `postgres` | PostgreSQL 16 | Incidents, KPIs, audit log |
| Object storage | local dir / S3 | — | Trigger-time clip segments |
| Dashboard | `ui` | React, Vite, Tailwind, canvas | Live view, site map, reports UI |

## 3. Latency Budget (end-to-end)

Target: **< 1.5 s from physical event to dashboard alert**; agent enrichment adds up to 30 s (async).

| Stage | Budget | Notes |
| --- | --- | --- |
| RTSP decode (per stream) | ≤ 20 ms/frame | hardware decode where available; 3 streams |
| Detection | ≤ 15 ms/frame batch | planned as YOLO11s INT8, batch 3–4; **measured** (single stream, 1080p): YOLO11s FP16 TensorRT p50 9.4 ms / p95 16.0 ms, FP32 p50 20.7 ms. INT8 and batching were never built (docs/benchmarks.md) |
| Tracking + state | ≤ 3 ms/track | ByteTrack, CPU-able |
| Homography + rules | ≤ 2 ms/track | precomputed polygons, vectorized Shapely/NumPy |
| Telemetry publish | ≤ 5 ms | Redis XADD, fire-and-forget |
| Broker → API → browser | ≤ 100 ms | WebSocket push |
| **Deterministic alert total** | **≤ ~500 ms** | hard interlock class alarm fires here |
| Agent triage (async) | 5–30 s | queued; not in alert path |

**As built:** the deterministic half holds (rules run every frame and a `TriggerEvent` lands on
the Redis `trigger_events` stream as soon as a rule fires), but **no alarm consumer exists**:
nothing sounds a buzzer or pushes an alert off that stream. A person sees the incident only when
it appears on the dashboard, after agent verification and the Band-3 gate. Measured agent triage
p50 was 75.6 s (M3) and 68.8 s (M5), not 5–30 s. What the design does guarantee as built: the agent
can't suppress a trigger, because a timeout, crash, or bad answer still produces a
`needs_review` incident. Wiring an alarm consumer to `trigger_events` is the missing piece for a
true sub-second alert path.

## 4. Data Flow Contracts

- **TrackletFrame** (every ~100 ms per camera): camera_id, frame ts, list of tracks
  (track_id, class, confidence, bbox, ground point [x,y] m, velocity [vx,vy] m/s, zone ids).
- **TriggerEvent**: rule_id, severity, involved track ids, snapshot of last N tracklets,
  trigger-time metrics (min distance, dwell time), clip reference.
- **IncidentRecord**: agent output, strictly Pydantic-validated; includes verified kinematics,
  narrative, severity, regulatory rationale, and the TriggerEvent evidence pointer.

Full schemas: `06-schemas-and-api.md`.

## 5. Key Design Decisions

| Decision | Rationale | ADR |
| --- | --- | --- |
| Two planes (fast/slow) with schema boundary | Safety latency + determinism vs context/synthesis | ADR-001 |
| Redis Streams locally; cloud queues in reference arch | $0 local dev; cloud-native mapping | ADR-002 |
| YOLO11 family default; RT-DETR optional | FPS/accuracy balance on modest GPU | ADR-003 |
| Cloud delivered as IaC + runbooks | Cost discipline; documentation is the deliverable | ADR-004 |
| Downsample telemetry to ~10 Hz for bus | 30–60 FPS detection is intra-process; bus load control | — |

## 6. Failure Modes & Degradation

| Failure | Behavior |
| --- | --- |
| Agent worker down / LLM provider down | Fast path fully unaffected; triggers queue (Redis stream retention 1 h locally, SQS 1 day in cloud); dashboard shows "reasoning delayed" |
| Camera stream drop | Ingestion watchdog emits `stream.health` event; dashboard marks camera offline |
| Detector drift / low confidence | Confidence gating configurable per camera; agent can propose threshold changes (human-approved) |
| Broker down | Vision worker buffers last N tracklet frames in memory, reconnects with backoff |
| Schema mismatch | Versioned schemas; consumer rejects + DLQs malformed payloads; CI schema-compat tests |

## 7. Scaling Path (documented, not exercised)

- Horizontal: one vision worker per GPU; camera→worker assignment via config or partitioned queue.
- Broker: Redis Streams → Kafka (MSK) for >50 streams; identical message schemas.
- Agent: queue-depth-driven autoscaling (Fargate service / Cloud Run / KEDA on Container Apps).
- Storage: PostgreSQL → partitioned tables; clip lifecycle rules on object storage.
