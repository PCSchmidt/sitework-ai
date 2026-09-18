# 13 — Architecture Diagrams (C4 + sequence)

These diagrams describe the system **as actually built and verified**, not the original design
aspiration — where the two differ (video overlay/2D canvas, Shift Synthesizer, PPE/forklift
fine-tunes), that's called out inline rather than drawn as if it exists. See
`docs/02-system-architecture.md` §1's "Implementation status" note for the full list. Complements
the flowchart in the [README](../README.md#architecture-at-a-glance), which shows the same fast/slow
path split at module granularity; this doc adds the C4 levels above it and the sequence below it.

## C4 Level 1 — System Context

Who and what SiteWatch AI talks to, with no internals shown.

```mermaid
flowchart TB
    OPERATOR["Safety Manager / Operator<br>(person)"]
    CAMERAS["Site cameras<br>(simulated: MediaMTX loops 3 demo clips as RTSP;<br>real RTSP cameras supported, not deployed anywhere)"]
    LLM["LLM Provider<br>(OpenRouter / Z.ai / local Ollama —<br>OpenAI-compatible base URL)"]
    CLOUD["Reference cloud environments<br>(AWS / GCP / Azure —<br>Terraform validated, never applied, ADR-004)"]

    subgraph SYS["SiteWatch AI"]
        SW["Dual-plane safety intelligence system:<br>deterministic fast path + LLM-verified slow path<br>+ delivery plane (API/dashboard)"]
    end

    CAMERAS -- "RTSP video" --> SYS
    SYS -- "REST + WebSocket<br>incident feed, KPIs, evidence" --> OPERATOR
    OPERATOR -- "review decisions<br>(needs_review queue)" --> SYS
    SYS -- "per-incident RPC prompt<br>(trajectory/classification verification)" --> LLM
    LLM -- "schema-validated result.json" --> SYS
    SYS -. "Terraform (authored, fmt/validate only)<br>no live deployment" .-> CLOUD
```

## C4 Level 2 — Containers

The real `docker-compose.yml` services (local, $0), plus the parallel `docker-compose.replay.yml`
stack (also $0) that substitutes for the GPU/LLM containers when the only goal is a live-looking
public demo (docs/12-roadmap.md M6).

```mermaid
flowchart TB
    subgraph ingestion["Ingestion"]
        MEDIAMTX["mediamtx<br>RTSP server, loops demo MP4s"]
    end

    subgraph fastpath["Fast path (per-camera GPU containers)"]
        VISION["vision-dock / vision-aisle / vision-yard<br>pipelines/vision/pipeline.py<br>YOLO11s + ByteTrack + Kalman + homography + RuleEngine"]
    end

    subgraph broker["Broker"]
        REDIS[("redis<br>Streams: tracklets:{camera_id}, trigger_events")]
    end

    subgraph slowpath["Slow path (event-driven)"]
        AGENT["agent<br>agent/worker.py + prime_adapter.py + band3.py<br>drives prime-agent RPC, Band-3 gate"]
    end

    subgraph delivery["Delivery plane"]
        API["api<br>FastAPI REST + WS, Postgres LISTEN/NOTIFY"]
        UI["ui<br>React/Vite dashboard"]
    end

    PG[("postgres<br>incidents, reviews, agent_runs")]

    MEDIAMTX -- RTSP --> VISION
    VISION -- "XADD tracklets" --> REDIS
    VISION -- "XADD trigger_events" --> REDIS
    VISION -- "writes tracks.jsonl / clip.mp4" --> VOL[("agent_workspace volume")]
    REDIS -- "consumer group read" --> AGENT
    AGENT -- "reads evidence" --> VOL
    AGENT -- "IncidentRecord upsert + agent_run" --> PG
    PG -- "NOTIFY" --> API
    API -- "reads evidence (read-only mount)" --> VOL
    API -- "REST + WS" --> UI

    subgraph replaystack["docker-compose.replay.yml -- $0 public demo (M6), replaces everything above except postgres/api/ui"]
        REPLAY["replay<br>scripts/replay_demo.py<br>pure Python, no GPU, no LLM call"]
    end
    REPLAY -. "IncidentRecord upsert<br>(same repository.py call)" .-> PG
```

## Sequence — real incident (confirmed and needs_review paths)

The actual `agent/worker.py` flow (docs/05 §3), including the Band-3 rejection branch that's a
first-class outcome, not an error case.

```mermaid
sequenceDiagram
    participant V as "vision-* (fast path)"
    participant R as "Redis (trigger_events)"
    participant W as agent/worker.py
    participant PA as "prime-agent (RPC)"
    participant B3 as agent/band3.py
    participant PG as Postgres
    participant API as api/main.py
    participant UI as React dashboard

    V->>R: XADD TriggerEvent (rule fired, e.g. proximity < 1.0m)
    W->>R: XREADGROUP (consumer group, crash-safe)
    W->>W: write event.json + tracks.jsonl to incident dir
    W->>PA: prompt() -- trajectory/classification verification
    Note over W,PA: external wall-clock timeout+kill (210s)<br>-- the --autonomous-max-turns flag alone<br>did NOT stop a runaway task (spike-01 Finding 4)
    PA-->>W: result.json (KinematicsVerdict)
    W->>B3: check(event, verdict, tracks.jsonl)
    alt Band-3 passes
        B3-->>W: passed=true
        W->>PG: upsert_incident(state=confirmed) + agent_run
    else Band-3 mismatch (or timeout / bad schema)
        B3-->>W: passed=false, reasons=[...]
        W->>PG: upsert_incident(state=needs_review, rejection_reason)
        Note over PG: raw evidence retained either way -- never dropped
    end
    PG->>API: NOTIFY (trigger on incidents table)
    API->>UI: WS push (incident.created / incident.updated)
    UI->>API: GET /api/v1/incidents/{id}/evidence/tracks|clip
    Note over UI: operator can accept/reject/re-queue<br>from the needs_review queue
```

## Sequence — replay mode ($0 public demo, M6)

The same Postgres → API → WS → dashboard path, entered without a GPU vision container or an LLM
call anywhere in the loop.

```mermaid
sequenceDiagram
    participant F as "evaluation/fixtures/incidents/* (30 hand-labeled M5 fixtures)"
    participant RP as scripts/replay_demo.py
    participant PG as Postgres
    participant API as api/main.py
    participant UI as React dashboard

    loop every --interval-s (default 8s), cycling through fixtures
        RP->>F: load event.json + tracks.jsonl + expected.json
        RP->>RP: stage_evidence() -- copy tracks.jsonl to workspace/incidents/{replay_id}/
        alt proximity fixture (2 involved tracks)
            RP->>RP: agent.band3.recompute_kinematics(tracks) -- real recomputation,<br>same math the Band-3 gate itself uses
        end
        RP->>RP: build_record() -- classification/state from expected.json<br>(the fixture's own hand-labeled ground truth);<br>narrative_md tagged [REPLAY DEMO];<br>agent_run = 0 tokens, model="replay-mode (no LLM call)"
        RP->>PG: upsert_incident() (same repository.py call a real incident uses)
    end
    PG->>API: NOTIFY
    API->>UI: WS push (incident.created)
    UI->>API: GET /api/v1/incidents/{id}/evidence/tracks
```

## What these diagrams deliberately don't show

- **Video + boxes overlay / 2D site canvas** — not built (needs `frame.ticker`, live track
  positions over WS, still unwired per `docs/02-system-architecture.md` §1). The dashboard's real
  live surface today is the incident feed, needs_review queue, KPI bar, and evidence viewer.
- **Shift Synthesizer sub-agent** — not built. `api/reports.py` (shown nowhere above, since it's a
  pure-function HTML renderer, not a message in this flow) stitches together each incident's own
  already-written `narrative_md` for a time window; it is not a new scheduled agent invocation.
- **A live/hosted instance of any of this** — none exists. `docker-compose.replay.yml` describes a
  stack anyone can run locally at $0; it is not itself a public URL.
