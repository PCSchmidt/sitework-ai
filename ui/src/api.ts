import { assetUrl, STATIC_DEMO } from './config'
import type { Camera, IncidentRecord, Kpis } from './types'

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`)
  return (await resp.json()) as T
}

// Static demo (GitHub Pages): the agent's real incident records, recorded offline by
// scripts/showcase_agent.py, stand in for the API. Filters/KPIs are applied here.
let staticIncidents: Promise<IncidentRecord[]> | null = null
function loadStaticIncidents(): Promise<IncidentRecord[]> {
  staticIncidents ??= fetch(assetUrl('showcase/incidents.json'))
    .then(json<IncidentRecord[]>)
    .then((list) => [...list].sort((a, b) => b.trigger_ts - a.trigger_ts))
  return staticIncidents
}

export function fetchIncidents(params: {
  state?: string
  camera?: string
  limit?: number
} = {}): Promise<IncidentRecord[]> {
  if (STATIC_DEMO) {
    return loadStaticIncidents().then((list) =>
      list
        .filter((i) => !params.state || i.state === params.state)
        .filter((i) => !params.camera || i.camera_id === params.camera)
        .slice(0, params.limit ?? 100),
    )
  }
  const qs = new URLSearchParams()
  if (params.state) qs.set('state', params.state)
  if (params.camera) qs.set('camera', params.camera)
  qs.set('limit', String(params.limit ?? 100))
  return fetch(`/api/v1/incidents?${qs}`).then(json<IncidentRecord[]>)
}

export function fetchIncident(eventId: string): Promise<IncidentRecord> {
  if (STATIC_DEMO) {
    return loadStaticIncidents().then((list) => {
      const found = list.find((i) => i.event_id === eventId)
      if (!found) throw new Error(`404 ${eventId}`)
      return found
    })
  }
  return fetch(`/api/v1/incidents/${encodeURIComponent(eventId)}`).then(json<IncidentRecord>)
}

export function fetchKpis(windowHours = 24): Promise<Kpis> {
  if (STATIC_DEMO) {
    return loadStaticIncidents().then((list) => {
      const count = (key: (i: IncidentRecord) => string | null) =>
        list.reduce<Record<string, number>>((acc, i) => {
          const k = key(i)
          if (k) acc[k] = (acc[k] ?? 0) + 1
          return acc
        }, {})
      return {
        window_hours: windowHours,
        total_incidents: list.length,
        by_classification: count((i) => i.classification),
        by_state: count((i) => i.state),
      }
    })
  }
  return fetch(`/api/v1/kpis?window=${windowHours}`).then(json<Kpis>)
}

export function fetchCameras(): Promise<Camera[]> {
  if (STATIC_DEMO) {
    return fetch(assetUrl('showcase/index.json'))
      .then(json<Array<{ camera_id: string }>>)
      .then((rows) => rows.map((r) => ({ ...r, id: r.camera_id })))
  }
  return fetch('/api/v1/cameras').then(json<Camera[]>)
}

export function submitReview(
  eventId: string,
  reviewer: string,
  decision: string,
  note?: string,
): Promise<{ status: string }> {
  if (STATIC_DEMO) return Promise.reject(new Error('reviews are disabled in the recorded demo'))
  return fetch(`/api/v1/incidents/${encodeURIComponent(eventId)}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewer, decision, note }),
  }).then(json<{ status: string }>)
}

export function evidenceTracksUrl(eventId: string): string {
  if (STATIC_DEMO) return assetUrl(`showcase/evidence/${encodeURIComponent(eventId)}/tracks.jsonl`)
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
