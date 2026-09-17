import type { Camera, IncidentRecord, Kpis } from './types'

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`)
  return (await resp.json()) as T
}

export function fetchIncidents(params: {
  state?: string
  camera?: string
  limit?: number
} = {}): Promise<IncidentRecord[]> {
  const qs = new URLSearchParams()
  if (params.state) qs.set('state', params.state)
  if (params.camera) qs.set('camera', params.camera)
  qs.set('limit', String(params.limit ?? 100))
  return fetch(`/api/v1/incidents?${qs}`).then(json<IncidentRecord[]>)
}

export function fetchIncident(eventId: string): Promise<IncidentRecord> {
  return fetch(`/api/v1/incidents/${encodeURIComponent(eventId)}`).then(json<IncidentRecord>)
}

export function fetchKpis(windowHours = 24): Promise<Kpis> {
  return fetch(`/api/v1/kpis?window=${windowHours}`).then(json<Kpis>)
}

export function fetchCameras(): Promise<Camera[]> {
  return fetch('/api/v1/cameras').then(json<Camera[]>)
}

export function submitReview(
  eventId: string,
  reviewer: string,
  decision: string,
  note?: string,
): Promise<{ status: string }> {
  return fetch(`/api/v1/incidents/${encodeURIComponent(eventId)}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewer, decision, note }),
  }).then(json<{ status: string }>)
}

export function evidenceTracksUrl(eventId: string): string {
  return `/api/v1/incidents/${encodeURIComponent(eventId)}/evidence/tracks`
}

export function evidenceClipUrl(eventId: string): string {
  return `/api/v1/incidents/${encodeURIComponent(eventId)}/evidence/clip`
}

export function shiftReportUrl(fromTs: number, toTs: number): string {
  return `/api/v1/shift-report?from_ts=${fromTs}&to_ts=${toTs}`
}

export function liveWsUrl(): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}/live/ws`
}
