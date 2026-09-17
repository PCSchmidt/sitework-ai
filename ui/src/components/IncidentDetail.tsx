import { useState } from 'react'
import { evidenceClipUrl, evidenceTracksUrl, submitReview } from '../api'
import type { IncidentRecord } from '../types'

function Stat({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-mono text-sm">{value ?? '—'}</div>
    </div>
  )
}

export function IncidentDetail({ incident }: { incident: IncidentRecord }) {
  const [reviewer, setReviewer] = useState('')
  const [decision, setDecision] = useState('accepted')
  const [note, setNote] = useState('')
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [clipMissing, setClipMissing] = useState(false)

  const submit = async () => {
    if (!reviewer.trim()) return
    setStatus('saving')
    try {
      await submitReview(incident.event_id, reviewer.trim(), decision, note.trim() || undefined)
      setStatus('saved')
    } catch {
      setStatus('error')
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="font-mono text-sm text-slate-400">{incident.event_id}</h2>
        <h1 className="text-xl font-semibold">{incident.camera_id}</h1>
      </div>

      <div className="grid grid-cols-3 gap-3 bg-slate-900 border border-slate-800 rounded-lg p-4">
        <Stat label="Severity" value={incident.severity} />
        <Stat label="State" value={incident.state} />
        <Stat label="Classification" value={incident.classification} />
        <Stat label="Min distance (m)" value={incident.verified_kinematics?.verified_min_distance_m ?? null} />
        <Stat label="Closing velocity (m/s)" value={incident.verified_kinematics?.closing_velocity_mps ?? null} />
        <Stat label="TTC (s)" value={incident.verified_kinematics?.ttc_s ?? null} />
      </div>

      {incident.narrative_md && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="text-xs text-slate-500 mb-1">Narrative</div>
          <p className="whitespace-pre-wrap text-sm">{incident.narrative_md}</p>
        </div>
      )}

      {incident.rejection_reason && (
        <div className="bg-amber-950/40 border border-amber-800 rounded-lg p-4">
          <div className="text-xs text-amber-400 mb-1">Needs review — reason</div>
          <p className="whitespace-pre-wrap text-sm">{incident.rejection_reason}</p>
        </div>
      )}

      {incident.recommended_actions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {incident.recommended_actions.map((a) => (
            <span key={a} className="text-xs px-2 py-1 rounded-full bg-slate-800 text-slate-300">
              {a}
            </span>
          ))}
        </div>
      )}

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
        <div className="text-xs text-slate-500 mb-2">Evidence</div>
        {!clipMissing ? (
          <video
            key={incident.event_id}
            controls
            className="w-full rounded-md bg-black max-h-72"
            src={evidenceClipUrl(incident.event_id)}
            onError={() => setClipMissing(true)}
          />
        ) : (
          <p className="text-sm text-slate-500">No clip captured for this incident.</p>
        )}
        <a
          href={evidenceTracksUrl(incident.event_id)}
          target="_blank"
          rel="noreferrer"
          className="inline-block mt-2 text-xs text-sky-400 hover:underline"
        >
          View tracks.jsonl
        </a>
      </div>

      {incident.state === 'needs_review' && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="text-xs text-slate-500 mb-2">Record review decision</div>
          <div className="flex flex-col gap-2">
            <input
              className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-sm"
              placeholder="Reviewer name"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
            />
            <select
              className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-sm"
              value={decision}
              onChange={(e) => setDecision(e.target.value)}
            >
              <option value="accepted">Accept agent verdict</option>
              <option value="rejected">Reject — false alarm</option>
              <option value="escalated">Escalate</option>
            </select>
            <textarea
              className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-sm"
              placeholder="Note (optional)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
            />
            <button
              onClick={submit}
              disabled={!reviewer.trim() || status === 'saving'}
              className="bg-slate-100 text-slate-900 rounded px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            >
              {status === 'saving' ? 'Saving…' : 'Submit review'}
            </button>
            {status === 'saved' && <p className="text-xs text-emerald-400">Recorded.</p>}
            {status === 'error' && <p className="text-xs text-red-400">Failed to save — try again.</p>}
          </div>
        </div>
      )}
    </div>
  )
}
