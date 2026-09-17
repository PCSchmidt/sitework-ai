import type { IncidentRecord, IncidentState } from '../types'

const STATE_FILTERS: Array<{ label: string; value: IncidentState | 'all' }> = [
  { label: 'All', value: 'all' },
  { label: 'Needs review', value: 'needs_review' },
  { label: 'Confirmed', value: 'confirmed' },
]

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'bg-red-500',
  high: 'bg-orange-500',
  medium: 'bg-yellow-500',
  low: 'bg-slate-500',
}

function formatTs(ts: number): string {
  return new Date(ts * 1000).toLocaleString()
}

export function IncidentList({
  incidents,
  filter,
  onFilterChange,
  selectedId,
  onSelect,
}: {
  incidents: IncidentRecord[]
  filter: IncidentState | 'all'
  onFilterChange: (f: IncidentState | 'all') => void
  selectedId: string | null
  onSelect: (eventId: string) => void
}) {
  const filtered = filter === 'all' ? incidents : incidents.filter((i) => i.state === filter)

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 mb-3">
        {STATE_FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => onFilterChange(f.value)}
            className={`text-xs px-3 py-1 rounded-full border ${
              filter === f.value
                ? 'bg-slate-100 text-slate-900 border-slate-100'
                : 'border-slate-700 text-slate-300 hover:border-slate-500'
            }`}
          >
            {f.label}
            {f.value === 'needs_review' && (
              <span className="ml-1 opacity-70">
                ({incidents.filter((i) => i.state === 'needs_review').length})
              </span>
            )}
          </button>
        ))}
      </div>
      <div className="overflow-y-auto flex-1 flex flex-col gap-2 pr-1">
        {filtered.length === 0 && (
          <p className="text-sm text-slate-500">No incidents in this filter yet.</p>
        )}
        {filtered.map((incident) => (
          <button
            key={incident.event_id}
            onClick={() => onSelect(incident.event_id)}
            className={`text-left rounded-lg border px-3 py-2 transition-colors ${
              selectedId === incident.event_id
                ? 'border-slate-400 bg-slate-800'
                : 'border-slate-800 bg-slate-900 hover:border-slate-600'
            }`}
          >
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${SEVERITY_COLOR[incident.severity] ?? 'bg-slate-500'}`} />
              <span className="font-mono text-xs text-slate-400 truncate">{incident.event_id}</span>
            </div>
            <div className="text-sm mt-1">{incident.camera_id}</div>
            <div className="flex items-center justify-between text-xs text-slate-500 mt-1">
              <span>{formatTs(incident.trigger_ts)}</span>
              <span
                className={
                  incident.state === 'needs_review' ? 'text-amber-400' : 'text-slate-400'
                }
              >
                {incident.state}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
