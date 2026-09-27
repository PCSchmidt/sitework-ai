// Recorded fast-path output written by pipelines/vision/record.py
// (ui/public/showcase/{camera_id}/showcase.json + index.json), kept in sync by hand.

export type Point = [number, number]

export interface ShowcaseTrack {
  id: number
  cls: string
  conf: number
  bbox: [number, number, number, number] // x1, y1, x2, y2 in source-video pixels
  g: Point | null // ground point, meters (null without calibration)
  speed: number | null // m/s, only with a calibration that passes the gate
  zones: string[]
}

export interface ShowcaseFrame {
  t: number // clip-relative seconds
  tracks: ShowcaseTrack[]
  // reference-frame px -> this frame's px (first 8 entries of a 3x3, h33 = 1);
  // present only for a panning camera with motion compensation
  cam?: number[]
}

export interface ShowcaseZone {
  id: string
  kind: string
  polygon_m: Point[]
  polygon_px: Point[] // in the calibration's reference frame
}

export interface ShowcaseRule {
  id: string
  kind: string
  description: string
  citation: string | null
  zone_ids: string[]
  radius_m: number | null
  duration_s: number | null
  dwell_s: number | null
  limit_mps: number | null
}

export interface ShowcaseEvent {
  t: number
  trigger_ts: number
  event_id: string
  rule_id: string
  kind: string
  description: string
  citation: string | null
  severity: string
  track_ids: number[]
  metrics: Record<string, number>
}

export interface CalibrationSummary {
  method: string
  rms_px: number
  valid: boolean
  rms_gate_px: number
  camera_height_m_assumed?: number
  focal_length_px_assumed?: number
  depth_lines_used?: number
  assumptions?: Record<string, string>
  [key: string]: unknown
}

export interface Showcase {
  camera_id: string
  name: string
  note: string | null
  video: string
  source_clip: string
  fps: number
  width: number
  height: number
  duration_s: number
  detector: { weights: string; imgsz: number; confidence_gate: number }
  publish_hz: number
  calibration: CalibrationSummary | null
  zones: ShowcaseZone[]
  rules: ShowcaseRule[]
  events: ShowcaseEvent[]
  frames: ShowcaseFrame[]
}

export interface ShowcaseIndexRow {
  camera_id: string
  name: string
  note: string | null
  duration_s: number
  events: number
  calibration: { method: string; valid: boolean } | null
}

/** Index of the last frame whose timestamp is <= t (0 if t precedes every frame). */
export function frameIndexAt(frames: ShowcaseFrame[], t: number): number {
  let lo = 0
  let hi = frames.length - 1
  if (hi < 0 || t <= frames[0].t) return 0
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (frames[mid].t <= t) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** Apply a 3x3 homography given as its first 8 entries (h33 = 1). */
export function applyH(h: number[], [x, y]: Point): Point {
  const w = h[6] * x + h[7] * y + 1
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w]
}

export function bottomCenter(bbox: ShowcaseTrack['bbox']): Point {
  return [(bbox[0] + bbox[2]) / 2, bbox[3]]
}

export function distanceM(a: Point, b: Point): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1])
}

export const VEHICLE_CLASSES = new Set(['vehicle', 'heavy_vehicle', 'forklift'])

export const CLASS_COLOR: Record<string, string> = {
  person: '#34d399',
  forklift: '#f59e0b',
  heavy_vehicle: '#f59e0b',
  vehicle: '#60a5fa',
}

export function classColor(cls: string): string {
  return CLASS_COLOR[cls] ?? '#cbd5e1'
}

export const CLASS_LABEL: Record<string, string> = {
  person: 'person',
  heavy_vehicle: 'heavy vehicle',
  vehicle: 'vehicle',
  forklift: 'forklift',
}

/**
 * The closest person-vehicle pair in a frame with both ground points, restricted to
 * tracks inside at least one of `zoneIds` (empty = anywhere), or null.
 */
export function closestPair(
  frame: ShowcaseFrame,
  zoneIds: string[],
): { person: ShowcaseTrack; vehicle: ShowcaseTrack; distance: number } | null {
  const inZone = (tr: ShowcaseTrack) =>
    zoneIds.length === 0 || tr.zones.some((z) => zoneIds.includes(z))
  const people = frame.tracks.filter((tr) => tr.cls === 'person' && tr.g && inZone(tr))
  const vehicles = frame.tracks.filter((tr) => VEHICLE_CLASSES.has(tr.cls) && tr.g && inZone(tr))
  let best: { person: ShowcaseTrack; vehicle: ShowcaseTrack; distance: number } | null = null
  for (const person of people) {
    for (const vehicle of vehicles) {
      const d = distanceM(person.g!, vehicle.g!)
      if (!best || d < best.distance) best = { person, vehicle, distance: d }
    }
  }
  return best
}

export function formatClock(t: number): string {
  const s = Math.max(0, t)
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
}

// agent/transcript.py's compact transcript of one prime-agent session.
export interface TranscriptStep {
  kind: 'thought' | 'tool'
  text?: string
  tool?: string | null
  code?: string | null
  args?: Record<string, unknown> | null
  output?: string | null
  status?: string | null
  ms?: number | null
}

export interface AgentTranscript {
  turns: number
  model: string | null
  steps: TranscriptStep[]
}
