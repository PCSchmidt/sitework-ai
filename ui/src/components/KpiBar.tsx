import { useEffect, useState } from 'react'
import { fetchKpis } from '../api'
import type { Kpis } from '../types'

export function KpiBar() {
  const [kpis, setKpis] = useState<Kpis | null>(null)

  useEffect(() => {
    const load = () => fetchKpis(24).then(setKpis).catch(() => setKpis(null))
    load()
    const id = window.setInterval(load, 30_000)
    return () => window.clearInterval(id)
  }, [])

  if (!kpis) return null

  const cards: Array<[string, number]> = [
    ['Total (24h)', kpis.total_incidents],
    ['Confirmed', kpis.by_state['confirmed'] ?? 0],
    ['Needs review', kpis.by_state['needs_review'] ?? 0],
    ['Near-miss', kpis.by_classification['near_miss'] ?? 0],
  ]

  return (
    <div className="flex gap-3 flex-wrap">
      {cards.map(([label, n]) => (
        <div key={label} className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-2 min-w-[120px]">
          <div className="text-xl font-bold">{n}</div>
          <div className="text-xs text-slate-400">{label}</div>
        </div>
      ))}
    </div>
  )
}
