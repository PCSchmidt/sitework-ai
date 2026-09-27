import { useEffect, useMemo, useState } from 'react'
import type { IncidentRecord } from '../types'
import { formatClock } from '../showcase/model'
import { useShowcase, useShowcaseIndex } from '../showcase/useShowcase'
import { ShowcasePlayer, type SeekRequest } from './ShowcasePlayer'

const LEAD_IN_S = 3.0

/**
 * If this incident came from a recorded camera clip, play that clip cued just before
 * the rule fired, and lay the two planes' answers side by side: what the deterministic
 * rule measured, what the agent verified in code, and whether the Band-3 gate agreed.
 * Returns null for incidents with no recording (e.g. live-stack incidents).
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

  useEffect(() => {
    if (event) setSeek({ t: Math.max(0, event.t - LEAD_IN_S), nonce: Date.now() })
  }, [event])

  if (!showcase || !event) return null
  const k = incident.verified_kinematics

  return (
    <div className="flex flex-col gap-3">
      <ShowcasePlayer
        key={incident.event_id}
        showcase={showcase}
        seek={seek}
        maxHeightVh={48}
      />
      <div className="grid md:grid-cols-3 gap-3 text-sm">
        <Plane
          title="Fast plane · deterministic rule"
          tone="red"
          lines={[
            `${event.rule_id} fired at ${formatClock(event.t)} in the clip`,
            ...Object.entries(event.metrics).map(
              ([key, v]) => `${key.replace(/_/g, ' ')}: ${v}`,
            ),
            `severity hint: ${event.severity}`,
          ]}
        />
        <Plane
          title="Slow plane · agent verified in Python"
          tone="sky"
          lines={
            k
              ? [
                  `classification: ${k.classification}`,
                  k.verified_min_distance_m !== null
                    ? `recomputed min distance: ${k.verified_min_distance_m} m`
                    : 'no pairwise distance for this rule kind',
                  k.closing_velocity_mps !== null
                    ? `closing velocity: ${k.closing_velocity_mps} m/s`
                    : 'closing velocity: n/a',
                  incident.agent_run
                    ? `${incident.agent_run.turns} turns · ${(incident.agent_run.wall_ms / 1000).toFixed(0)} s · ${incident.agent_run.tokens_in + incident.agent_run.tokens_out} tokens`
                    : '',
                ].filter(Boolean)
              : ['no verified result (see reason below)']
          }
        />
        <Plane
          title="Band-3 gate · deterministic recheck"
          tone={incident.state === 'confirmed' ? 'emerald' : 'amber'}
          lines={
            incident.state === 'confirmed'
              ? [
                  'passed: recomputed from tracks.jsonl and matched within tolerance',
                  `state: ${incident.state}`,
                ]
              : ['rejected, sent to a human', incident.rejection_reason ?? '']
          }
        />
      </div>
    </div>
  )
}

const TONES = {
  red: 'border-red-900 bg-red-950/30 text-red-300',
  sky: 'border-sky-900 bg-sky-950/30 text-sky-300',
  emerald: 'border-emerald-900 bg-emerald-950/30 text-emerald-300',
  amber: 'border-amber-900 bg-amber-950/30 text-amber-300',
}

function Plane({
  title,
  tone,
  lines,
}: {
  title: string
  tone: keyof typeof TONES
  lines: string[]
}) {
  return (
    <div className={`rounded-lg border p-3 ${TONES[tone]}`}>
      <div className="text-xs font-semibold mb-1.5">{title}</div>
      <ul className="flex flex-col gap-0.5 text-xs text-slate-300">
        {lines.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </div>
  )
}
