-- Postgres schema for the M4 delivery plane (docs/06 §6).
--
-- Only the tables that need real persistence are here: `incidents` (the
-- Band-3-gated output of agent/worker.py), `reviews` (human review-queue
-- decisions, docs/05 §8), and `agent_runs` (cognitive-plane observability --
-- logged for every incident attempt, confirmed or not, so the agent's
-- false-positive/failure rate is dashboard-visible per docs/05 §7).
--
-- `cameras`/`zones`/`rules` are deliberately NOT duplicated here -- they're
-- already the config/*.yaml files, loaded and validated at startup
-- (pipelines/config/loader.py); the API serves them directly from config,
-- not from a second, driftable copy in the database.
--
-- Idempotent: safe to run on every API startup (api/db.py).

CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id TEXT UNIQUE NOT NULL,
    camera_id TEXT NOT NULL,
    trigger_ts DOUBLE PRECISION NOT NULL,
    severity TEXT NOT NULL,
    state TEXT NOT NULL,
    classification TEXT,
    verified_kinematics JSONB,
    rejection_reason TEXT,
    narrative_md TEXT NOT NULL DEFAULT '',
    rule_citations TEXT[] NOT NULL DEFAULT '{}',
    recommended_actions TEXT[] NOT NULL DEFAULT '{}',
    evidence_refs TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_incidents_trigger_ts ON incidents (trigger_ts DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_camera_id ON incidents (camera_id);
CREATE INDEX IF NOT EXISTS idx_incidents_state ON incidents (state);

CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    note TEXT,
    at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reviews_incident_id ON reviews (incident_id);

-- incident_id is nullable: a run that crashed/timed out before producing any
-- IncidentRecord is still worth logging (docs/05 §7's false-positive-rate
-- visibility depends on seeing failed runs, not just successful ones).
CREATE TABLE IF NOT EXISTS agent_runs (
    id SERIAL PRIMARY KEY,
    incident_id UUID REFERENCES incidents (id) ON DELETE SET NULL,
    event_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'trajectory_inspector',
    model TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    turns INTEGER NOT NULL DEFAULT 0,
    wall_ms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_event_id ON agent_runs (event_id);

-- Used by api/main.py's WS incident push (LISTEN/NOTIFY, docs/06 §5).
CREATE OR REPLACE FUNCTION notify_incident_change() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify(
        'incident_change',
        json_build_object('event_id', NEW.event_id, 'op', TG_OP)::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS incidents_notify ON incidents;
CREATE TRIGGER incidents_notify
    AFTER INSERT OR UPDATE ON incidents
    FOR EACH ROW EXECUTE FUNCTION notify_incident_change();
