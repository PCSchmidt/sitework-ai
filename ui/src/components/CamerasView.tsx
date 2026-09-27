import { useEffect, useState } from 'react'
import { fetchIncident } from '../api'
import { formatClock, type Showcase } from '../showcase/model'
import {
  useAgentTranscript,
  useEarlierRuns,
  useShowcase,
  useShowcaseIndex,
} from '../showcase/useShowcase'
import type { IncidentRecord } from '../types'
import { ShowcasePlayer, type SeekRequest } from './ShowcasePlayer'
import { SiteMap } from './SiteMap'
import { AgentConsole, PlaneStrip, RunPicker, useSlowPlaneReplay } from './TwoPlanes'

function useIncident(eventId: string | null): IncidentRecord | null {
  const [incident, setIncident] = useState<IncidentRecord | null>(null)
  useEffect(() => {
    setIncident(null)
    if (!eventId) return
    let live = true
    fetchIncident(eventId)
      .then((i) => live && setIncident(i))
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [eventId])
  return incident
}

export function CamerasView({ initialCamera }: { initialCamera?: string | null }) {
  const { rows, error } = useShowcaseIndex()
  const [cameraId, setCameraId] = useState<string | null>(initialCamera ?? null)
  const { showcase, error: loadError } = useShowcase(cameraId)
  const [time, setTime] = useState(0)
  const [seek, setSeek] = useState<SeekRequest | null>(null)
  const event = showcase?.events[0] ?? null
  const latestIncident = useIncident(event?.event_id ?? null)
  const latestTranscript = useAgentTranscript(event?.event_id ?? null)
  const earlier = useEarlierRuns(event?.event_id ?? null)
  const [run, setRun] = useState(0)
  const incident = run > 0 && earlier[run - 1] ? earlier[run - 1].incident : latestIncident
  const transcript = run > 0 && earlier[run - 1] ? earlier[run - 1].transcript : latestTranscript
  const replay = useSlowPlaneReplay(event, time, transcript, incident)
  useEffect(() => setRun(0), [cameraId])
  const pickRun = (i: number) => {
    setRun(i)
    if (event) setSeek({ t: Math.max(0, event.t - 3), nonce: Date.now() })
  }

  useEffect(() => {
    if (!cameraId && rows && rows.length > 0) setCameraId(rows[0].camera_id)
  }, [rows, cameraId])
  useEffect(() => {
    if (initialCamera) setCameraId(initialCamera)
  }, [initialCamera])

  if (error) {
    return (
      <p className="text-sm text-slate-500">
        No camera recordings found ({error}). Generate them with{' '}
        <code className="text-slate-300">pipelines.vision.record</code>.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {rows?.map((row) => (
          <button
            key={row.camera_id}
            onClick={() => setCameraId(row.camera_id)}
            className={`text-left rounded-lg border px-3 py-2 min-w-[210px] ${
              row.camera_id === cameraId
                ? 'border-slate-400 bg-slate-800'
                : 'border-slate-800 bg-slate-900 hover:border-slate-600'
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-sm">{row.camera_id}</span>
              {row.events > 0 && (
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-red-600/80">
                  {row.events} rule {row.events === 1 ? 'firing' : 'firings'}
                </span>
              )}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">{row.name}</div>
            <div className="text-[11px] mt-1">
              <CalibrationChip calibration={row.calibration} />
            </div>
          </button>
        ))}
      </div>

      {loadError && <p className="text-sm text-red-400">Could not load recording: {loadError}</p>}
      {showcase && (
        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px] gap-4">
          <div className="xl:col-span-2 flex flex-col gap-2">
            <RunPicker earlier={earlier} selected={run} onSelect={pickRun} />
            <PlaneStrip showcase={showcase} time={time} event={event} incident={incident} replay={replay} />
          </div>
          <div className="flex flex-col gap-3 min-w-0">
            <ShowcasePlayer key={showcase.camera_id} showcase={showcase} seek={seek} onTime={setTime} />
            {showcase.note && <p className="text-sm text-slate-400">{showcase.note}</p>}
            <EventList
              showcase={showcase}
              onSeek={(t) => setSeek({ t: Math.max(0, t - 2.5), nonce: Date.now() })}
            />
          </div>
          <div className="flex flex-col gap-3 min-w-0">
            <AgentConsole
              showcase={showcase}
              event={event}
              incident={incident}
              transcript={transcript}
              replay={replay}
              className="h-[360px]"
            />
            <div>
              <div className="text-xs text-slate-500 mb-1">Floor plan (meters, from the calibration)</div>
              <div className="aspect-square xl:aspect-auto xl:h-[300px]">
                <SiteMap showcase={showcase} time={time} />
              </div>
            </div>
          </div>
          <div className="xl:col-span-2">
            <CameraFacts showcase={showcase} />
          </div>
        </div>
      )}
    </div>
  )
}

export function CalibrationChip({
  calibration,
}: {
  calibration: { method: string; valid: boolean } | null
}) {
  if (!calibration) return <span className="text-slate-500">uncalibrated · detection only</span>
  return calibration.valid ? (
    <span className="text-emerald-400">calibrated · metric rules on</span>
  ) : (
    <span className="text-amber-400">unverified calibration · zone-only</span>
  )
}

function EventList({ showcase, onSeek }: { showcase: Showcase; onSeek: (t: number) => void }) {
  if (showcase.events.length === 0) {
    return (
      <p className="text-xs text-slate-500 border border-slate-800 rounded-lg p-3">
        No rule fired on this clip.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-slate-500">Rule firings (fast plane)</div>
      {showcase.events.map((e) => (
        <button
          key={e.event_id}
          onClick={() => onSeek(e.t)}
          className="text-left rounded-lg border border-red-900 bg-red-950/30 hover:border-red-600 p-3"
        >
          <div className="flex justify-between text-xs">
            <span className="font-mono text-red-300">{e.rule_id}</span>
            <span className="font-mono text-slate-400">{formatClock(e.t)}</span>
          </div>
          <div className="text-sm mt-1">{e.description}</div>
          <div className="text-xs text-slate-400 mt-1">
            {Object.entries(e.metrics)
              .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`)
              .join(' · ')}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">{e.citation}</div>
        </button>
      ))}
    </div>
  )
}

function CameraFacts({ showcase }: { showcase: Showcase }) {
  const cal = showcase.calibration
  return (
    <details className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm">
      <summary className="cursor-pointer text-slate-300">
        How this recording was made: detector, calibration, rules
      </summary>
      <div className="grid md:grid-cols-3 gap-4 mt-3 text-xs text-slate-300">
        <div>
          <div className="text-slate-500 mb-1">Detector + tracker</div>
          <p>
            {showcase.detector.weights} at {showcase.detector.imgsz}px, confidence ≥{' '}
            {showcase.detector.confidence_gate}, ByteTrack IDs. Every frame of{' '}
            <span className="font-mono">{showcase.source_clip}</span> ({showcase.fps} fps) was
            processed; rules ran at the live pipeline's {showcase.publish_hz} Hz.
          </p>
        </div>
        <div>
          <div className="text-slate-500 mb-1">Calibration</div>
          {cal ? (
            <>
              <p>
                Method <span className="font-mono">{cal.method}</span>, quality{' '}
                <span className="font-mono">{cal.rms_px >= 9999 ? 'not measured' : `${cal.rms_px} px`}</span>{' '}
                against a {cal.rms_gate_px} px gate:{' '}
                {cal.valid ? (
                  <span className="text-emerald-400">passes, metric rules enabled</span>
                ) : (
                  <span className="text-amber-400">fails, zone-only mode</span>
                )}
                .
              </p>
              {cal.assumptions && (
                <ul className="mt-2 flex flex-col gap-1.5 list-disc pl-4 text-slate-400">
                  {Object.entries(cal.assumptions).map(([k, v]) => (
                    <li key={k}>
                      <span className="font-mono text-slate-300">{k}</span>: {v}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <p>None. Boxes and track IDs only; no floor positions, zones, or rules.</p>
          )}
        </div>
        <div>
          <div className="text-slate-500 mb-1">Rules on this camera</div>
          {showcase.rules.length === 0 ? (
            <p>None.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {showcase.rules.map((r) => (
                <li key={r.id}>
                  <span className="font-mono text-slate-200">{r.id}</span>: {r.description}{' '}
                  <span className="text-slate-500">
                    ({[
                      r.radius_m && `radius ${r.radius_m} m`,
                      r.duration_s && `for ${r.duration_s} s`,
                      r.dwell_s && `dwell ${r.dwell_s} s`,
                      r.limit_mps && `limit ${r.limit_mps} m/s`,
                    ]
                      .filter(Boolean)
                      .join(', ')})
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </details>
  )
}
