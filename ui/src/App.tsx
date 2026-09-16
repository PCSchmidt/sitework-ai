import { useEffect, useState } from 'react'

export default function App() {
  const [health, setHealth] = useState<string>('…')

  useEffect(() => {
    fetch('/healthz')
      .then((r) => r.json())
      .then((b) => setHealth(b.status))
      .catch(() => setHealth('unreachable'))
  }, [])

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-8">
      <h1 className="text-2xl font-bold">SiteWatch AI</h1>
      <p className="mt-2 text-slate-400">
        M0 scaffold — delivery plane lands in M4 (live boxes, 2D site canvas, incident feed,
        needs_review queue).
      </p>
      <p className="mt-4">
        API health: <span className="font-mono">{health}</span>
      </p>
    </main>
  )
}
