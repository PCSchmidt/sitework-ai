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

`calibration_quality.valid` is computed at emission time as `rms_px ≤ 2.0` (hard gate, see
`04-data-and-models.md` §3). Rules requiring metric distance must declare
`min_calibration_quality` in `config/zones.yaml` and degrade to zone-only semantics when
`valid == false`.

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
  "cooldown_key": "dock_north_01:proximity_forklift_pedestrian:42+77",
  "calibration_quality": {"rms_px": 1.4, "valid": true}
}
```

## 3. Agent outputs (slow path → Band-3 gate → DB)

- `KinematicsVerdict`: verified_min_distance_m, closing_velocity_mps, ttc_s (nullable),
  classification ∈ {normal_ops, near_miss, violation, false_positive}, `recompute_inputs` echo.
- `IncidentRecord`: event_id, timestamps, severity ∈ enum, `state` ∈ {confirmed, needs_review}
  (docs/05 §8), `classification`/`verified_kinematics` (nullable -- absent for a rejected incident
  rather than fabricated), `rejection_reason` (nullable, set only when `state=needs_review`),
  narrative_md, rule_citations[], recommended_actions[], evidence refs, agent_run stats.

### Band-3 gate (normative)

Recompute metrics from `tracks.jsonl` with the same deterministic functions the fast path used;
reject on mismatch. **Tolerances:** |Δdistance| ≤ 0.15 m, |Δvelocity| ≤ 0.2 m/s,
|Δtime| ≤ 0.2 s — or 5% relative, whichever is larger.

- **Fields cross-checked (as implemented in `agent/band3.py`):** for proximity triggers (exactly
  two involved tracks), the recomputed minimum distance is compared against both the fast path's
  `metrics.min_distance_m` and the agent's `verified_min_distance_m`, and the recomputed closing
  velocity against the agent's `closing_velocity_mps`. For zone-intrusion triggers (one track;
  added at M7) the gate recomputes the track's continuous in-zone dwell at the trigger frame from
  the stored `zone_ids` and rejects a verdict that contradicts it: `violation` when the dwell
  limit (from `config/rules.yaml`) isn't met, `false_positive` when it is, within the 0.2 s time
  tolerance. `normal_ops`/`near_miss` pass as judgment calls, and the fast path's own
  `duration_s` claim is deliberately not gated, so the agent can still correctly refute a wrong
  trigger. Speed triggers still pass on schema validation alone, and `ttc_s` is not
  cross-checked.
- **Timestamp alignment:** nearest frame within 50 ms; the stored tracklet window is replayed at
  identical sample indices — no interpolation, no re-tracking.
- **Rounding:** comparisons on float64; no early rounding in either implementation.

## 4. REST API (FastAPI, `api/main.py`)

As implemented (every route below exists and is covered by `tests/test_api.py`):

| Method/Path | Purpose |
| --- | --- |
| `GET /healthz` | liveness; returns 200 only after startup has created the schema |
| `GET /api/v1/incidents?from_ts=&to_ts=&severity=&camera=&state=&limit=&offset=` | paged incident list, newest first |
| `GET /api/v1/incidents/{event_id}` | one full `IncidentRecord` |
| `POST /api/v1/incidents/{event_id}/review` | record a human review decision (`reviewer`, `decision`, optional `note`) |
| `GET /api/v1/incidents/{event_id}/evidence/tracks` | the incident's `tracks.jsonl`, parsed to JSON |
| `GET /api/v1/incidents/{event_id}/evidence/clip` | the incident's `clip.mp4` (404 when none was captured) |
| `GET /api/v1/cameras` / `GET /api/v1/cameras/{id}/health` | camera config; health returns `status: unknown` (the stream watchdog was never built) |
| `GET /api/v1/zones` / `GET /api/v1/rules` | geofences and rule definitions, served straight from `config/*.yaml` |
| `GET /api/v1/kpis?window=` | incident counts by classification and by state over the last `window` hours |
| `GET /api/v1/shift-report?from_ts=&to_ts=` | HTML report stitching together each incident's own narrative for the window |
| `WS /live/ws` | incident push (see §5) |

`event_id` is regex-validated before it's used in a filesystem path, so evidence routes can't be
used for path traversal.

**Designed but not built:** a scheduled, agent-written shift audit (`GET /shifts/{date}/report`,
md/pdf; the shift-report route above is its deterministic stand-in), and KPIs for dwell time
and PPE adherence (PPE detection doesn't exist).

## 5. WebSocket protocol

As implemented: the server pushes `incident.created` and `incident.updated`, driven by a
Postgres `LISTEN`/`NOTIFY` trigger on the `incidents` table. There is no replay on reconnect;
the dashboard re-fetches over REST after a dropped connection.

**Designed but not built:** `frame.ticker` (live track positions for a site map, ~2 Hz) and
`stream.health`, plus client `subscribe {camera_ids}`. `frame.ticker` is the missing piece
behind the dashboard's absent video/bounding-box overlay and 2D site canvas (docs/02 §1).

## 6. PostgreSQL schema (`api/schema.sql`)

As implemented, three tables plus a notify trigger. The schema is idempotent and applied on
every API startup:

```sql
incidents(id uuid PK, event_id text UNIQUE, camera_id, trigger_ts, severity, state,
          classification NULL, verified_kinematics jsonb NULL, rejection_reason NULL,
          narrative_md, rule_citations text[], recommended_actions text[],
          evidence_refs text[], created_at);
reviews(id PK, incident_id FK -> incidents, reviewer, decision, note, at);
agent_runs(id PK, incident_id FK NULL, event_id, kind, model, tokens_in, tokens_out,
           turns, wall_ms, status, created_at);   -- logged for every attempt, incl. crashes
-- trigger incidents_notify: pg_notify('incident_change', {event_id, op}) on INSERT/UPDATE
```

Cameras, zones, and rules are deliberately **not** tables: they stay in `config/*.yaml` and the
API serves them from there, so there's one source of truth instead of two copies that can drift.
Incidents are written by upsert on `event_id`, so a reprocessed trigger updates its row rather
than duplicating it.

**Designed but not built:** `cameras`/`zones` tables (superseded by the config-file decision
above), `tracks` and `track_frames` (evidence windows are stored as `tracks.jsonl` files on the
shared workspace volume instead), and the retention policy (30-day windows, 7-day clip
lifecycle). Nothing is expired automatically today.

## 7. Config files

- `config/cameras.yaml`: rtsp urls, decode params, per-camera confidence gates.
- `config/zones.yaml`: polygons (ground-plane meters), zone kind, `active`, and
  `min_calibration_quality`.
- `config/rules.yaml`: rule ids, kind, human-readable descriptions, compliance citation strings,
  zone bindings, the rule parameters (`radius_m`, `duration_s`, `dwell_s`, `limit_mps`,
  `cooldown_s`), and an optional `severity` that overrides the per-kind default (e.g. a 5 m
  warning tier at `medium` next to a 3 m rule at the default `high`). Cooldowns are per rule id,
  so tiers of the same kind don't mute each other.
- `config/calibration/{camera_id}.json`: the pixel → ground homography, its method
  (`points`, `vanishing_point`, `level_camera`), `rms_px` and the gate result, any stated
  assumptions, and optionally the `reference_image` it was made on (enables per-frame motion
  compensation). Written by `pipelines/geometry/calibrate.py` from a `*.points.json`,
  `*.lines.json` or `*.setup.json` input kept alongside.
- `config/shifts.yaml`: shift windows. Schema-validated by `tests/test_config.py`, but nothing
  consumes it yet: it was meant to drive the (unbuilt) Shift Synthesizer's shift boundaries, and
  the shift-report route takes an explicit `from_ts`/`to_ts` instead.
- Each config is validated against its Pydantic model when a process loads it; bad config ⇒ fail
  fast (`pipelines/config/loader.py`).
