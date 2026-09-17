import { useEffect, useState } from 'react'
import { shiftReportUrl } from './api'
import { IncidentDetail } from './components/IncidentDetail'
import { IncidentList } from './components/IncidentList'
import { KpiBar } from './components/KpiBar'
import { useLiveIncidents } from './hooks/useLiveIncidents'
import type { IncidentState } from './types'

export default function App() {
  const { incidents, connected, loading, error } = useLiveIncidents()
  const [filter, setFilter] = useState<IncidentState | 'all'>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    if (!selectedId && incidents.length > 0) setSelectedId(incidents[0].event_id)
  }, [incidents, selectedId])

  const selected = incidents.find((i) => i.event_id === selectedId) ?? null

  const now = Math.floor(Date.now() / 1000)
  const shiftStart = now - 12 * 3600

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-6 flex flex-col gap-4">
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">SiteWatch AI</h1>
          <p className="text-sm text-slate-400">
            Live incident feed — deterministic detection, agent-verified kinematics.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-xs text-slate-400">
            <span
              className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-red-500'}`}
            />
            {connected ? 'live' : 'reconnecting…'}
          </span>
          <a
            href={shiftReportUrl(shiftStart, now)}
            target="_blank"
            rel="noreferrer"
            className="text-xs px-3 py-1.5 rounded-full border border-slate-700 hover:border-slate-500"
          >
            Shift report (last 12h)
          </a>
        </div>
      </header>

      <KpiBar />

      {error && (
        <p className="text-sm text-red-400">Could not load incidents: {error}</p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[360px_1fr] gap-4 flex-1 min-h-0">
        <section className="bg-slate-900/40 border border-slate-800 rounded-lg p-3 min-h-[400px] lg:h-[calc(100vh-220px)]">
          {loading ? (
            <p className="text-sm text-slate-500">Loading incidents…</p>
          ) : (
            <IncidentList
              incidents={incidents}
              filter={filter}
              onFilterChange={setFilter}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </section>

        <section className="bg-slate-900/40 border border-slate-800 rounded-lg p-4 overflow-y-auto lg:h-[calc(100vh-220px)]">
          {selected ? (
            <IncidentDetail incident={selected} />
          ) : (
            <p className="text-sm text-slate-500">Select an incident to see details.</p>
          )}
        </section>
      </div>
    </main>
  )
}
