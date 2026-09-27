import { useEffect, useMemo, useState } from 'react'
import type { IncidentRecord } from '../types'
import {
  useAgentTranscript,
  useEarlierRuns,
  useShowcase,
  useShowcaseIndex,
} from '../showcase/useShowcase'
import { ShowcasePlayer, type SeekRequest } from './ShowcasePlayer'
import { AgentConsole, PlaneStrip, RunPicker, useSlowPlaneReplay } from './TwoPlanes'

const LEAD_IN_S = 3.0

/**
 * If this incident came from a recorded camera clip: the two-plane strip on top, the clip
 * cued just before the rule fired, and the agent's recorded REPL session beside it, which
 * starts replaying the moment the video reaches the firing. Returns null for incidents
 * with no recording (e.g. live-stack incidents).
 */
export function IncidentPlayback({ incident }: { incident: IncidentRecord }) {
  const { rows } = useShowcaseIndex()
  const recorded = rows?.some((r) => r.camera_id === incident.camera_id) ?? false
  const { showcase } = useShowcase(recorded ? incident.camera_id : null)
  const event = useMemo(
    () => showcase?.events.find((e) => e.event_id === incident.event_id) ?? null,
    [showcase, incident.event_id],
  )
  const [seek, setSeek] = useState<SeekRequest | null>(null)
  const [time, setTime] = useState(0)
  const latestTranscript = useAgentTranscript(event?.event_id ?? null)
  const earlier = useEarlierRuns(event?.event_id ?? null)
  const [run, setRun] = useState(0)
  const shownIncident = run > 0 && earlier[run - 1] ? earlier[run - 1].incident : incident
  const transcript = run > 0 && earlier[run - 1] ? earlier[run - 1].transcript : latestTranscript
  const replay = useSlowPlaneReplay(event, time, transcript, shownIncident)

  useEffect(() => {
    setRun(0)
    if (event) setSeek({ t: Math.max(0, event.t - LEAD_IN_S), nonce: Date.now() })
  }, [event])

  const pickRun = (i: number) => {
    setRun(i)
    if (event) setSeek({ t: Math.max(0, event.t - LEAD_IN_S), nonce: Date.now() })
  }

  if (!showcase || !event) return null

  return (
    <div className="flex flex-col gap-3">
      <RunPicker earlier={earlier} selected={run} onSelect={pickRun} />
      <PlaneStrip showcase={showcase} time={time} event={event} incident={shownIncident} replay={replay} />
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] gap-3">
        <ShowcasePlayer key={incident.event_id} showcase={showcase} seek={seek} onTime={setTime} />
        <div className="relative min-h-[260px]">
          <AgentConsole
            showcase={showcase}
            event={event}
            incident={shownIncident}
            transcript={transcript}
            replay={replay}
            className="h-[360px] xl:h-auto xl:absolute xl:inset-0"
          />
        </div>
      </div>
    </div>
  )
}
