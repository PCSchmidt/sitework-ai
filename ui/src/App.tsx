import { useEffect, useState } from 'react'
import { shiftReportUrl } from './api'
import { CamerasView } from './components/CamerasView'
import { IncidentDetail } from './components/IncidentDetail'
import { IncidentList } from './components/IncidentList'
import { KpiBar } from './components/KpiBar'
import { REPO_URL, STATIC_DEMO } from './config'
import { useLiveIncidents } from './hooks/useLiveIncidents'
import type { IncidentState } from './types'

type Tab = 'incidents' | 'cameras'

function tabFromHash(): Tab {
  return window.location.hash === '#cameras' ? 'cameras' : 'incidents'
}

export default function App() {
  const { incidents, connected, loading, error } = useLiveIncidents()
  const [filter, setFilter] = useState<IncidentState | 'all'>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>(tabFromHash)

  useEffect(() => {
    if (!selectedId && incidents.length > 0) setSelectedId(incidents[0].event_id)
  }, [incidents, selectedId])

  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const selectTab = (next: Tab) => {
    setTab(next)
    window.history.replaceState(null, '', next === 'cameras' ? '#cameras' : '#')
  }

  const selected = incidents.find((i) => i.event_id === selectedId) ?? null

  const now = Math.floor(Date.now() / 1000)
  const shiftStart = now - 12 * 3600

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-4 sm:p-6 flex flex-col gap-4">
      {STATIC_DEMO && <DemoBanner />}
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">SiteWatch AI</h1>
          <p className="text-sm text-slate-400">
            Computer vision flags it in milliseconds; an AI agent checks the math before anyone is
            paged.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {STATIC_DEMO ? (
            <a
              href={REPO_URL}
              target="_blank"
              rel="noreferrer"
              className="text-xs px-3 py-1.5 rounded-full border border-slate-700 hover:border-slate-500"
            >
              Source on GitHub
            </a>
          ) : (
            <>
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
            </>
          )}
        </div>
      </header>

      <nav className="flex gap-1 border-b border-slate-800">
        {(
          [
            ['incidents', 'Incidents'],
            ['cameras', 'Cameras · computer vision'],
          ] as Array<[Tab, string]>
        ).map(([id, label]) => (
          <button
            key={id}
            onClick={() => selectTab(id)}
            className={`px-4 py-2 text-sm -mb-px border-b-2 ${
              tab === id
                ? 'border-sky-400 text-slate-100'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === 'cameras' ? (
        <CamerasView />
      ) : (
        <>
          <KpiBar />

          {error && <p className="text-sm text-red-400">Could not load incidents: {error}</p>}

          <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4 flex-1 min-h-0">
            <section className="bg-slate-900/40 border border-slate-800 rounded-lg p-3 min-h-[240px] lg:h-[calc(100vh-260px)]">
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

            <section className="bg-slate-900/40 border border-slate-800 rounded-lg p-4 overflow-y-auto lg:h-[calc(100vh-260px)]">
              {selected ? (
                <IncidentDetail incident={selected} />
              ) : (
                <p className="text-sm text-slate-500">Select an incident to see details.</p>
              )}
            </section>
          </div>
        </>
      )}
    </main>
  )
}

function DemoBanner() {
  return (
    <div className="rounded-lg border border-sky-800 bg-sky-950/40 px-4 py-3 text-sm text-sky-100">
      <strong className="font-semibold">Recorded demo.</strong> Everything here is real output
      from the SiteWatch pipeline, captured offline because a static page can't run a GPU or an
      LLM. YOLO11s detection, ByteTrack tracking, camera calibration and the deterministic rules
      ran on every frame of each clip. The agent verdicts come from real Prime Agent runs checked
      by the Band-3 gate.{' '}
      <a className="underline hover:text-white" href={REPO_URL} target="_blank" rel="noreferrer">
        Run it live from the repo
      </a>
      .
    </div>
  )
}
