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
|      -> Detector (YOLO11 / RT-DETR, TensorRT FP16/INT8)                  |
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
|    /root/.prime on NFS-class volume  |   |   (S3/GCS/Blob or local)  |
+--------------------------------------+   |  React/Vite dashboard:    |
                                            |   - video + boxes overlay |
                                            |   - 2D site canvas        |
                                            |   - incident feed         |
                                            +---------------------------+
```

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
| Detection | ≤ 15 ms/frame batch | YOLO11s INT8, batch=3–4 frames |
| Tracking + state | ≤ 3 ms/track | ByteTrack, CPU-able |
| Homography + rules | ≤ 2 ms/track | precomputed polygons, vectorized Shapely/NumPy |
| Telemetry publish | ≤ 5 ms | Redis XADD, fire-and-forget |
| Broker → API → browser | ≤ 100 ms | WebSocket push |
| **Deterministic alert total** | **≤ ~500 ms** | hard interlock class alarm fires here |
| Agent triage (async) | 5–30 s | queued; not in alert path |

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
