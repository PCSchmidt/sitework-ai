import { useEffect, useRef, useState } from 'react'
import { fetchIncidents, liveWsUrl } from '../api'
import type { IncidentRecord, WsMessage } from '../types'

/**
 * Loads the incident list via REST, then keeps it live via `/live/ws`
 * (`incident.created`/`incident.updated` pushes, docs/06 §5). Reconnects
 * with backoff on drop rather than leaving the feed silently stale --
 * the WS server itself has no replay, so a dropped connection needs a
 * REST re-fetch, not just a raw reconnect, to catch up on anything missed
 * while disconnected.
 */
export function useLiveIncidents() {
  const [incidents, setIncidents] = useState<IncidentRecord[]>([])
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const refetchTimer = useRef<number | null>(null)

  const reload = () => {
    fetchIncidents({ limit: 200 })
      .then((list) => {
        setIncidents(list)
        setError(null)
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    reload()

    let ws: WebSocket | null = null
    let closedByUs = false
    let retryMs = 1000

    const connect = () => {
      ws = new WebSocket(liveWsUrl())
      ws.onopen = () => {
        setConnected(true)
        retryMs = 1000
      }
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as WsMessage
        if (msg.type === 'incident.created' || msg.type === 'incident.updated') {
          setIncidents((prev) => {
            const without = prev.filter((i) => i.event_id !== msg.data.event_id)
            return [msg.data, ...without].sort((a, b) => b.trigger_ts - a.trigger_ts)
          })
        }
      }
      ws.onclose = () => {
        setConnected(false)
        if (closedByUs) return
        // a missed push during the gap wouldn't otherwise be reflected
        if (refetchTimer.current) window.clearTimeout(refetchTimer.current)
        refetchTimer.current = window.setTimeout(() => {
          reload()
          connect()
        }, retryMs)
        retryMs = Math.min(retryMs * 2, 15000)
      }
      ws.onerror = () => ws?.close()
    }
    connect()

    return () => {
      closedByUs = true
      if (refetchTimer.current) window.clearTimeout(refetchTimer.current)
      ws?.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { incidents, connected, loading, error, reload }
}
