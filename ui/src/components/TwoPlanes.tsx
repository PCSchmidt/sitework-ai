import { useEffect, useRef, useState } from 'react'
import type { IncidentRecord } from '../types'
import {
  frameIndexAt,
  type AgentTranscript,
  type Showcase,
  type ShowcaseEvent,
  type TranscriptStep,
} from '../showcase/model'

// The replay compresses the agent's real run so a visitor can watch it; the real
// duration is always shown next to it.
const HANDOFF_MS = 900
const GATE_MS = 1600
const MIN_REPLAY_MS = 7000
const MAX_REPLAY_MS = 16000
const EVENT_EPS_S = 0.05

export type Phase = 'watching' | 'handoff' | 'agent' | 'gate' | 'done'

export interface Replay {
  phase: Phase
  shownSteps: number
  totalSteps: number
  speedup: number
  restart: () => void
  skip: () => void
}

/**
 * Drives the slow-plane replay off the video clock: nothing happens until the video
 * reaches the rule firing (the fast plane's decision); then the evidence "hands off",
 * the agent's recorded REPL steps appear one by one, the gate rechecks, and the outcome
 * lands. Seeking back before the firing resets it, exactly as if the rule hadn't fired.
 */
export function useSlowPlaneReplay(
  event: ShowcaseEvent | null,
  time: number,
  transcript: AgentTranscript | null,
  incident: IncidentRecord | null,
): Replay {
  const fired = event !== null && time >= event.t - EVENT_EPS_S
  const totalSteps = transcript?.steps.length ?? 0
  const realMs = incident?.agent_run?.wall_ms ?? 0
  const replayMs = Math.min(MAX_REPLAY_MS, Math.max(MIN_REPLAY_MS, realMs / 5))
  const endMs = HANDOFF_MS + replayMs + GATE_MS
  const start = useRef<number | null>(null)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!fired) {
      start.current = null
      setElapsed(0)
      return
    }
    if (start.current === null) start.current = performance.now()
    const id = window.setInterval(() => {
      if (start.current === null) return
      const e = performance.now() - start.current
      setElapsed(e)
      if (e > endMs) window.clearInterval(id)
    }, 100)
    return () => window.clearInterval(id)
  }, [fired, endMs])

  let phase: Phase = 'watching'
  if (fired) {
    if (elapsed < HANDOFF_MS) phase = 'handoff'
    else if (elapsed < HANDOFF_MS + replayMs) phase = 'agent'
    else if (elapsed < endMs) phase = 'gate'
    else phase = 'done'
  }
  const agentElapsed = Math.max(0, elapsed - HANDOFF_MS)
  const shownSteps =
    phase === 'watching' || phase === 'handoff'
      ? 0
      : phase === 'agent'
        ? Math.min(totalSteps, Math.floor((agentElapsed / replayMs) * totalSteps) + 1)
        : totalSteps

  return {
    phase,
    shownSteps,
    totalSteps,
    speedup: realMs > 0 ? Math.max(1, Math.round(realMs / replayMs)) : 1,
    restart: () => {
      start.current = performance.now()
      setElapsed(0)
    },
    skip: () => {
      start.current = performance.now() - endMs - 1
      setElapsed(endMs + 1)
    },
  }
}

type StageState = 'idle' | 'active' | 'done' | 'alert'

const STAGE_STYLE: Record<StageState, string> = {
  idle: 'border-slate-800 bg-slate-900/60 text-slate-500',
  active: 'border-sky-400 bg-sky-950/60 text-slate-100 shadow-[0_0_0_3px_rgba(56,189,248,0.25)]',
  done: 'border-emerald-600 bg-emerald-950/40 text-slate-100',
  alert: 'border-red-500 bg-red-950/50 text-slate-100 shadow-[0_0_0_3px_rgba(239,68,68,0.25)]',
}

function Stage({
  n,
  title,
  subtitle,
  state,
  status,
}: {
  n: string
  title: string
  subtitle: string
  state: StageState
  status: string
}) {
  return (
    <div className={`rounded-lg border px-3 py-2 transition-all duration-300 ${STAGE_STYLE[state]}`}>
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide font-semibold">
        <span className="opacity-70">{n}</span>
        <span>{title}</span>
        {state === 'active' && <span className="ml-auto w-2 h-2 rounded-full bg-sky-400 animate-pulse" />}
      </div>
      <div className="hidden sm:block text-[11px] opacity-70">{subtitle}</div>
      <div className="text-xs mt-1 font-medium leading-snug">{status}</div>
    </div>
  )
}

function Arrow({ label, lit }: { label: string; lit: boolean }) {
  return (
    <div className="hidden lg:flex flex-col items-center justify-center gap-1 px-1 text-center">
      <span className={`text-lg leading-none ${lit ? 'text-amber-300 animate-pulse' : 'text-slate-600'}`}>
        →
      </span>
      <span className={`text-[10px] leading-tight max-w-[110px] ${lit ? 'text-amber-200' : 'text-slate-600'}`}>
        {label}
      </span>
    </div>
  )
}

/**
 * The dual-plane architecture as a live strip above the video: which plane is working
 * right now, what crossed between them, and what the gate decided.
 */
export function PlaneStrip({
  showcase,
  time,
  event,
  incident,
  replay,
}: {
  showcase: Showcase
  time: number
  event: ShowcaseEvent | null
  incident: IncidentRecord | null
  replay: Replay
}) {
  const frame = showcase.frames[frameIndexAt(showcase.frames, time)]
  const nTracks = frame?.tracks.length ?? 0
  const { phase } = replay
  const fired = phase !== 'watching'
  const confirmed = incident?.state === 'confirmed'
  const verdict = incident?.classification?.replace('_', ' ') ?? null

  const fastStatus = fired
    ? `RULE FIRED: ${event?.rule_id}`
    : `${nTracks} object${nTracks === 1 ? '' : 's'} tracked this frame · ${
        showcase.rules.length ? `${showcase.rules.length} rule${showcase.rules.length === 1 ? '' : 's'} watching` : 'no rules (uncalibrated)'
      }`

  let slowState: StageState = 'idle'
  let slowStatus = showcase.events.length
    ? 'Idle. Runs only when a rule fires; nothing sent to the LLM yet.'
    : 'Idle for this whole clip: no rule fires, so the agent never runs ($0).'
  if (phase === 'handoff') {
    slowState = 'active'
    slowStatus = 'Receiving the TriggerEvent + tracks.jsonl…'
  } else if (phase === 'agent') {
    slowState = 'active'
    slowStatus = replay.totalSteps
      ? `Verifying in its Python REPL · step ${replay.shownSteps}/${replay.totalSteps}`
      : 'Verifying in its Python REPL…'
  } else if (phase === 'gate' || phase === 'done') {
    // once the gate has spoken, an overruled verdict is marked as such
    slowState = phase === 'done' && incident?.state === 'needs_review' ? 'alert' : 'done'
    slowStatus = incident?.verified_kinematics
      ? `Verdict: ${incident.verified_kinematics.classification.replace('_', ' ')}${
          phase === 'done' && incident.state === 'needs_review' ? ' (overruled by the gate)' : ''
        }`
      : incident
        ? 'No usable verdict'
        : 'No recorded agent run for this event'
  }

  let gateState: StageState = 'idle'
  let gateStatus = 'Waits for the agent’s answer.'
  if (phase === 'gate') {
    gateState = 'active'
    gateStatus = 'Recomputing from tracks.jsonl in plain code…'
  } else if (phase === 'done') {
    gateState = !incident ? 'idle' : confirmed ? 'done' : 'alert'
    gateStatus = !incident
      ? '—'
      : confirmed
        ? 'Passed: the agent’s answer matches the recomputation'
        : 'Rejected: sent to a human reviewer'
  }

  let outState: StageState = 'idle'
  let outStatus = '—'
  if (phase === 'done' && incident) {
    outState = !confirmed || incident.classification === 'violation' ? 'alert' : 'done'
    outStatus = confirmed ? `Confirmed · ${verdict}` : 'Needs review'
  }

  return (
    <div className="grid grid-cols-2 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_0.8fr] gap-1.5 items-stretch">
      <Stage
        n="①"
        title="Fast plane"
        subtitle="Deterministic computer vision · every frame · no AI"
        state={fired ? 'alert' : 'active'}
        status={fastStatus}
      />
      <Arrow label="TriggerEvent + tracks.jsonl (never video)" lit={phase === 'handoff'} />
      <Stage
        n="②"
        title="Slow plane"
        subtitle="Prime Agent · Recursive Language Model"
        state={slowState}
        status={slowStatus}
      />
      <Arrow label="its verdict" lit={phase === 'gate'} />
      <Stage n="③" title="Band-3 gate" subtitle="Plain code rechecks the AI" state={gateState} status={gateStatus} />
      <Arrow label="" lit={phase === 'done'} />
      <Stage n="④" title="Record" subtitle="What gets stored" state={outState} status={outStatus} />
    </div>
  )
}

/** The agent's recorded REPL session, replayed step by step once the rule fires. */
export function AgentConsole({
  showcase,
  event,
  incident,
  transcript,
  replay,
  className = '',
}: {
  showcase: Showcase
  event: ShowcaseEvent | null
  incident: IncidentRecord | null
  transcript: AgentTranscript | null
  replay: Replay
  className?: string
}) {
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [replay.shownSteps, replay.phase])

  const run = incident?.agent_run
  let cell = 0
  const steps = transcript?.steps.slice(0, replay.shownSteps) ?? []

  return (
    <div className={`flex flex-col rounded-lg border border-slate-700 bg-[#0b1020] overflow-hidden ${className}`}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800 bg-slate-900/80">
        <span className="w-2.5 h-2.5 rounded-full bg-sky-400" />
        <span className="text-xs font-semibold">Slow plane · Prime Agent (RLM) · Python REPL</span>
        {replay.phase !== 'watching' && transcript && (
          <span className="ml-auto flex gap-1.5">
            <button onClick={replay.restart} className="text-[10px] px-2 py-0.5 rounded border border-slate-600 hover:border-slate-400">
              replay
            </button>
            <button onClick={replay.skip} className="text-[10px] px-2 py-0.5 rounded border border-slate-600 hover:border-slate-400">
              skip to verdict
            </button>
          </span>
        )}
      </div>
      {run && (
        <div className="px-3 py-1.5 text-[10px] text-slate-400 border-b border-slate-800">
          Real run: {(run.wall_ms / 1000).toFixed(0)} s · {run.turns} turns ·{' '}
          {(run.tokens_in + run.tokens_out).toLocaleString()} tokens
          {transcript?.model ? ` · ${transcript.model}` : ''} · replayed ~{replay.speedup}× faster
        </div>
      )}
      <div ref={scroller} className="flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed min-h-[220px]">
        {replay.phase === 'watching' && (
          <div className="text-slate-500 font-sans text-xs leading-relaxed">
            {showcase.events.length === 0 ? (
              <>
                No rule fires on this clip, so this session never starts. That's the design: the
                fast plane decides <em>whether</em> something happened, every frame, for free. The
                AI is only called when there's an incident to verify.
              </>
            ) : (
              <>
                Waiting. The fast plane is watching every frame; this agent starts only when a rule
                fires{event ? ` (at ${event.t.toFixed(1)} s in this clip)` : ''}. It then gets the
                trigger and the raw tracking data, and must answer by running code, not by
                guessing.
              </>
            )}
          </div>
        )}
        {replay.phase !== 'watching' && (
          <div className="text-amber-300/90 mb-2 font-sans text-xs">
            ▸ Trigger received: <span className="font-mono">{event?.rule_id}</span>. Task: recompute the
            claim from <span className="font-mono">tracks.jsonl</span> in Python, classify it, write{' '}
            <span className="font-mono">result.json</span>.
          </div>
        )}
        {replay.phase !== 'watching' && !transcript && (
          <div className="text-slate-500 font-sans text-xs">
            {incident ? 'No transcript was recorded for this run.' : 'No recorded agent run for this event.'}
          </div>
        )}
        {steps.map((step, i) => {
          if (step.kind === 'tool') cell += 1
          return <StepView key={i} step={step} cell={cell} />
        })}
        {(replay.phase === 'gate' || replay.phase === 'done') && incident && (
          <div className="mt-3 border-t border-slate-800 pt-2 font-sans text-xs">
            <div className="text-slate-400">
              <span className="text-emerald-300 font-semibold">Band-3 gate</span> (plain Python, not
              AI) recomputes from the same data:
            </div>
            {replay.phase === 'done' && (
              <div className={`mt-1 ${incident.state === 'confirmed' ? 'text-emerald-300' : 'text-amber-300'}`}>
                {incident.state === 'confirmed'
                  ? `✓ passed · stored as confirmed · ${incident.classification?.replace('_', ' ')}`
                  : `✗ rejected · stored as needs_review: ${incident.rejection_reason ?? ''}`}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function StepView({ step, cell }: { step: TranscriptStep; cell: number }) {
  const [open, setOpen] = useState(false)
  if (step.kind === 'thought') {
    return <div className="text-slate-300 font-sans text-xs italic my-2 whitespace-pre-wrap">{step.text}</div>
  }
  const output = step.output ?? ''
  const long = output.split('\n').length > 8 || output.length > 500
  const shown = open || !long ? output : output.split('\n').slice(0, 8).join('\n').slice(0, 500) + '\n…'
  return (
    <div className="my-2">
      <div className="text-sky-400">In [{cell}]:</div>
      <pre className="whitespace-pre-wrap break-words text-slate-100 bg-slate-900/70 rounded px-2 py-1">
        {step.code ?? JSON.stringify(step.args)}
      </pre>
      {output && (
        <>
          <div className={step.status === 'error' ? 'text-red-400' : 'text-slate-500'}>
            {step.status === 'error' ? 'Error (the agent sees this and corrects itself):' : 'Out:'}
          </div>
          <pre className={`whitespace-pre-wrap break-words px-2 ${step.status === 'error' ? 'text-red-300' : 'text-slate-300'}`}>
            {shown}
          </pre>
          {long && (
            <button onClick={() => setOpen(!open)} className="text-[10px] text-sky-400 hover:underline px-2">
              {open ? 'show less' : 'show all output'}
            </button>
          )}
        </>
      )}
    </div>
  )
}

/**
 * Pick which recorded agent run of this incident the strip and console show: the latest
 * one, or an earlier run kept on purpose (e.g. the one the Band-3 gate caught).
 */
export function RunPicker({
  earlier,
  selected,
  onSelect,
}: {
  earlier: Array<{ label: string; note: string }>
  selected: number
  onSelect: (index: number) => void
}) {
  if (earlier.length === 0) return null
  const options = ['Latest agent run', ...earlier.map((r) => r.label)]
  return (
    <div className="rounded-lg border border-amber-800/70 bg-amber-950/20 px-3 py-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-amber-200 font-semibold">This incident has more than one recorded agent run:</span>
        {options.map((label, i) => (
          <button
            key={label}
            onClick={() => onSelect(i)}
            className={`px-2.5 py-1 rounded-full border ${
              selected === i
                ? 'bg-amber-200 text-slate-900 border-amber-200'
                : 'border-amber-700 text-amber-100 hover:border-amber-400'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {selected > 0 && <p className="mt-1.5 text-amber-100/80">{earlier[selected - 1].note}</p>}
    </div>
  )
}
