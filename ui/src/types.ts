// Mirrors pipelines/schemas/models.py's IncidentRecord/AgentRunStats -- this
// is the wire format api/main.py serializes with `model_dump(mode="json")`,
// kept in sync by hand since there's no shared codegen step yet.

export type Severity = 'low' | 'medium' | 'high' | 'critical'
export type IncidentState = 'confirmed' | 'needs_review'
// pipelines/schemas/models.py's Classification StrEnum, kept in sync by hand.
export type Classification = 'normal_ops' | 'near_miss' | 'violation' | 'false_positive'

export interface KinematicsVerdict {
  verified_min_distance_m: number | null
  closing_velocity_mps: number | null
  ttc_s: number | null
  classification: Classification
  recompute_inputs: Record<string, string>
}

export interface AgentRunStats {
  model: string
  tokens_in: number
  tokens_out: number
  turns: number
  wall_ms: number
}

export interface IncidentRecord {
  event_id: string
  camera_id: string
  trigger_ts: number
  severity: Severity
  state: IncidentState
  classification: Classification | null
  verified_kinematics: KinematicsVerdict | null
  rejection_reason: string | null
  narrative_md: string
  rule_citations: string[]
  recommended_actions: string[]
  evidence_refs: string[]
  agent_run: AgentRunStats | null
}

export interface Kpis {
  window_hours: number
  total_incidents: number
  by_classification: Record<string, number>
  by_state: Record<string, number>
}

export interface Camera {
  id: string
  [key: string]: unknown
}

export type WsMessage =
  | { type: 'incident.created'; data: IncidentRecord }
  | { type: 'incident.updated'; data: IncidentRecord }
  | { type: 'pong' }
