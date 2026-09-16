# 06 — Event Schemas, API & Data Model

Schemas are the hard contract at the fast/slow boundary (ADR-001). Single source of truth:
`pipelines/schemas/` (Pydantic v2); JSON Schema exported to `schemas/` for the TS dashboard.

## 1. TrackletFrame (fast path → broker, ~10 Hz/camera)

```json
{
  "schema_version": "1.0",
  "camera_id": "dock_north_01",
  "frame_ts": 1789502400.12,
  "seq": 84213,
  "calibration_quality": {"rms_px": 1.4, "valid": true},
  "tracks": [
    {
      "track_id": 42,
      "cls": "forklift",
      "confidence": 0.91,
      "bbox_px": [120, 340, 260, 510],
      "ground_point_m": [14.2, 6.8],
      "velocity_mps": [1.2, 0.0],
      "speed_mps": 1.2,
      "state": {"cov_trace": 0.03, "age_frames": 512, "hits": 498},
      "zone_ids": ["dock_north"],
      "ppe": {"helmet": null, "vest": null}
    }
  ]
}
```

## 2. TriggerEvent (fast path → agent queue)

```json
{
  "schema_version": "1.0",
  "event_id": "evt_01J9ZK...",
  "trigger_ts": 1789502412.4,
  "camera_id": "dock_north_01",
  "rule_id": "proximity_forklift_pedestrian",
  "severity_hint": "high",
  "metrics": {"min_distance_m": 1.7, "duration_s": 4.2, "closing_speed_mps": 0.8},
  "involved_track_ids": [42, 77],
  "track_window_ref": "incidents/evt_01J9ZK.../tracks.jsonl",
  "clip_ref": "incidents/evt_01J9ZK.../clip.mp4",
  "cooldown_key": "dock_north_01:proximity:42+77",
  "calibration_quality": {"rms_px": 1.4, "valid": true}
}
```

## 3. Agent outputs (slow path → Band-3 gate → DB)

- `KinematicsVerdict`: verified_min_distance_m, closing_velocity_mps, ttc_s (nullable),
  classification ∈ {normal_ops, near_miss, violation, false_positive}, `recompute_inputs` echo.
- `IncidentRecord`: event_id, timestamps, verified kinematics, classification, severity ∈ enum,
  narrative_md, rule_citations[], recommended_actions[], evidence refs, agent_run stats.
  Band-3 gate: recompute metrics from `tracks.jsonl` with the same deterministic functions;
  mismatch > tolerance (0.1 m / 0.1 s) ⇒ reject.

## 4. REST API (FastAPI, `/api/v1`)

| Method/Path | Purpose |
| --- | --- |
| `GET /incidents?from=&to=&severity=&camera=` | paged incident list |
| `GET /incidents/{id}` | full record + evidence refs |
| `POST /incidents/{id}/review` | human review state transition |
| `GET /cameras` / `GET /cameras/{id}/health` | config + watchdog state |
| `GET /zones` / `GET /rules` | active geofences and rule definitions |
| `GET /shifts/{date}/report` | synthesized shift audit (md/pdf) |
| `GET /kpis?window=` | near-miss rate, dwell, PPE adherence |
| `GET /live/ws` (WS) | telemetry + incident push |

## 5. WebSocket protocol

Server pushes: `frame.ticker` (site-map track positions @2 Hz aggregated), `incident.created`,
`incident.updated`, `stream.health`. Client sends: `subscribe {camera_ids}`, `ping`.

## 6. PostgreSQL schema (core tables)

```sql
cameras(id PK, name, rtsp_url, calibration jsonb, created_at);
zones(id PK, camera_id FK, polygon jsonb, kind, active bool);
tracks(track_id, camera_id FK, cls, first_seen, last_seen, PK(track_id, camera_id));
track_frames(event_id FK, frame_ts, payload jsonb, PK(event_id, frame_ts));  -- triggered windows
incidents(id PK, event_id UNIQUE FK, camera_id FK, trigger_ts, severity, classification,
          verified_metrics jsonb, narrative_md text, rule_citations text[], state, created_at);
agent_runs(id PK, incident_id FK NULL, kind, model, tokens_in, tokens_out, turns,
           wall_ms, status, created_at);          -- observability of the cognitive plane
reviews(incident_id FK, reviewer, decision, note, at);
```

Retention: `track_frames` 30 days (only triggered windows are stored); incidents indefinite;
clips lifecycle-managed in object storage (7 days default, pinned for flagged incidents).

## 7. Config files

- `config/cameras.yaml`: rtsp urls, decode params, per-camera confidence gates.
- `config/zones.yaml`: polygons (ground-plane meters), rule bindings, dwell/proximity params,
  `min_calibration_quality`, `cooldown_s`.
- `config/rules.yaml`: rule ids, human-readable descriptions, compliance citation strings.
- All configs validated at startup against Pydantic settings models; bad config ⇒ fail fast.
