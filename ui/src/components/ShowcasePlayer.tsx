import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  applyH,
  bottomCenter,
  classColor,
  CLASS_LABEL,
  closestPair,
  formatClock,
  frameIndexAt,
  type Point,
  type Showcase,
  type ShowcaseEvent,
  type ShowcaseTrack,
} from '../showcase/model'
import { showcaseVideoUrl } from '../showcase/useShowcase'

// How long a fired rule stays highlighted on screen after its trigger time.
const EVENT_HOLD_S = 4.0
// A seek lands on the nearest decoded frame, which can sit a hair before the event time.
const EVENT_EPS_S = 0.05
const TRAIL_S = 1.5

export interface Layers {
  boxes: boolean
  labels: boolean
  trails: boolean
  zones: boolean
  distance: boolean
}

const DEFAULT_LAYERS: Layers = {
  boxes: true,
  labels: true,
  trails: true,
  zones: true,
  distance: true,
}

export interface SeekRequest {
  t: number
  nonce: number
}

interface Hover {
  track: ShowcaseTrack
  x: number // CSS px within the player
  y: number
}

/**
 * Plays a recorded clip with the fast plane's output drawn on top, frame by frame,
 * from showcase.json: boxes/labels/trails, zones (warped with the camera's motion),
 * the live worker-vehicle distance, and a banner when a rule fires. Everything drawn
 * is what pipelines/vision/record.py recorded -- nothing is computed here except
 * picking which recorded frame matches the video's current time.
 */
export function ShowcasePlayer({
  showcase,
  seek,
  autoPlay = true,
  onTime,
  maxHeightVh,
}: {
  showcase: Showcase
  seek?: SeekRequest | null
  autoPlay?: boolean
  onTime?: (t: number) => void
  // cap the video's height (it's sized by width otherwise) so content below stays visible
  maxHeightVh?: number
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const lastT = useRef(0)
  const onTimeRef = useRef(onTime)
  onTimeRef.current = onTime
  const [layers, setLayers] = useState<Layers>(DEFAULT_LAYERS)
  const [pauseOnFire, setPauseOnFire] = useState(true)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [rate, setRate] = useState(1)
  const [hover, setHover] = useState<Hover | null>(null)

  const proximityRule = showcase.rules.find((r) => r.kind === 'proximity')
  const metric = showcase.calibration?.valid === true
  const eventsByT = useMemo(
    () => [...showcase.events].sort((a, b) => a.t - b.t),
    [showcase.events],
  )

  const activeEvents = useCallback(
    (t: number): ShowcaseEvent[] =>
      eventsByT.filter((e) => t >= e.t - EVENT_EPS_S && t < e.t + EVENT_HOLD_S),
    [eventsByT],
  )

  const draw = useCallback(() => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return
    const t = video.currentTime
    const cw = canvas.clientWidth
    const ch = canvas.clientHeight
    const dpr = window.devicePixelRatio || 1
    if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
      canvas.width = Math.round(cw * dpr)
      canvas.height = Math.round(ch * dpr)
    }
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, cw, ch)

    const frames = showcase.frames
    if (frames.length === 0) return
    const idx = frameIndexAt(frames, t)
    const frame = frames[idx]
    const s = cw / showcase.width
    const px = ([x, y]: Point): Point => [x * s, y * s]
    // overlay text/strokes shrink on small players (phones) so they don't bury the video
    const u = Math.min(1, Math.max(0.65, cw / 900))
    const font = (weight: number, size: number) =>
      `${weight} ${Math.round(size * u)}px ui-sans-serif, system-ui`
    const fired = activeEvents(t)
    const firedTracks = new Set(fired.flatMap((e) => e.track_ids))
    const occupied = new Set(frame.tracks.flatMap((tr) => tr.zones))

    // zones, in reference-frame pixels warped onto this frame
    if (layers.zones) {
      for (const zone of showcase.zones) {
        if (zone.polygon_px.length < 3) continue
        const hot = occupied.has(zone.id)
        const firedHere = fired.some((e) =>
          showcase.rules.find((r) => r.id === e.rule_id)?.zone_ids.includes(zone.id),
        )
        ctx.beginPath()
        zone.polygon_px.forEach((p, i) => {
          const [x, y] = px(frame.cam ? applyH(frame.cam, p) : p)
          if (i === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        })
        ctx.closePath()
        const color = firedHere ? '239, 68, 68' : hot ? '250, 204, 21' : '56, 189, 248'
        ctx.fillStyle = `rgba(${color}, ${firedHere ? 0.22 : 0.12})`
        ctx.fill()
        ctx.lineWidth = 2
        ctx.setLineDash([8, 6])
        ctx.strokeStyle = `rgba(${color}, 0.9)`
        ctx.stroke()
        ctx.setLineDash([])
      }
    }

    // movement trails: bottom-center points over the last TRAIL_S seconds
    if (layers.trails) {
      const history = new Map<number, Point[]>()
      for (let i = idx; i >= 0 && frames[i].t >= t - TRAIL_S; i--) {
        for (const tr of frames[i].tracks) {
          const list = history.get(tr.id) ?? []
          list.push(px(bottomCenter(tr.bbox)))
          history.set(tr.id, list)
        }
      }
      for (const tr of frame.tracks) {
        const pts = history.get(tr.id)
        if (!pts || pts.length < 2) continue
        ctx.beginPath()
        pts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)))
        ctx.strokeStyle = classColor(tr.cls)
        ctx.globalAlpha = 0.55
        ctx.lineWidth = 3
        ctx.stroke()
        ctx.globalAlpha = 1
      }
    }

    // worker <-> vehicle distance, from the recorded ground points
    if (layers.distance && metric && proximityRule) {
      const pair = closestPair(frame, proximityRule.zone_ids)
      if (pair) {
        const radius = proximityRule.radius_m ?? Infinity
        const inside = pair.distance < radius
        const [x1, y1] = px(bottomCenter(pair.person.bbox))
        const [x2, y2] = px(bottomCenter(pair.vehicle.bbox))
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y2)
        ctx.strokeStyle = inside ? '#ef4444' : 'rgba(226, 232, 240, 0.85)'
        ctx.lineWidth = inside ? 3 : 2
        ctx.setLineDash(inside ? [] : [6, 5])
        ctx.stroke()
        ctx.setLineDash([])
        const label = `${pair.distance.toFixed(1)} m`
        const mx = (x1 + x2) / 2
        const my = (y1 + y2) / 2
        ctx.font = font(600, 13)
        const w = ctx.measureText(label).width + 12 * u
        ctx.fillStyle = inside ? '#ef4444' : 'rgba(15, 23, 42, 0.85)'
        ctx.fillRect(mx - w / 2, my - 11 * u, w, 22 * u)
        ctx.fillStyle = '#fff'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(label, mx, my)
        ctx.textAlign = 'start'
        ctx.textBaseline = 'alphabetic'
      }
    }

    // boxes + labels
    if (layers.boxes) {
      for (const tr of frame.tracks) {
        const [x1, y1] = px([tr.bbox[0], tr.bbox[1]])
        const [x2, y2] = px([tr.bbox[2], tr.bbox[3]])
        const flagged = firedTracks.has(tr.id)
        const color = flagged ? '#ef4444' : classColor(tr.cls)
        ctx.lineWidth = flagged ? 3 : 2
        ctx.strokeStyle = color
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
        if (hover?.track.id === tr.id) {
          ctx.fillStyle = 'rgba(255,255,255,0.08)'
          ctx.fillRect(x1, y1, x2 - x1, y2 - y1)
        }
        if (layers.labels) {
          const label = `${CLASS_LABEL[tr.cls] ?? tr.cls} #${tr.id} · ${tr.conf.toFixed(2)}`
          ctx.font = font(600, 12)
          const lh = 20 * u
          const w = ctx.measureText(label).width + 10 * u
          const ly = y1 > lh ? y1 - lh : y1
          ctx.fillStyle = color
          ctx.fillRect(x1, ly, w, lh)
          ctx.fillStyle = '#0f172a'
          ctx.fillText(label, x1 + 5 * u, ly + 14 * u)
        }
      }
    }

    // rule-fired banner
    if (fired.length > 0) {
      const e = fired[fired.length - 1]
      const radius = showcase.rules.find((r) => r.id === e.rule_id)?.radius_m
      const detail =
        e.metrics.min_distance_m !== undefined
          ? ` · within ${radius} m for ${e.metrics.duration_s?.toFixed(1)} s, closest ${e.metrics.min_distance_m.toFixed(1)} m`
          : e.metrics.duration_s !== undefined
            ? ` · in zone ${e.metrics.duration_s.toFixed(1)} s`
            : ''
      const title = `RULE FIRED · ${e.rule_id}${detail}`
      ctx.font = font(700, 15)
      const m = 12 * u
      const w = Math.min(cw - 2 * m, ctx.measureText(title).width + 28 * u)
      ctx.fillStyle = 'rgba(220, 38, 38, 0.92)'
      ctx.fillRect(m, m, w, 48 * u)
      ctx.fillStyle = '#fff'
      ctx.fillText(title, m + 14 * u, m + 20 * u, w - 28 * u)
      ctx.font = font(400, 12)
      ctx.fillText(e.citation ?? e.description, m + 14 * u, m + 38 * u, w - 28 * u)
    }
  }, [activeEvents, hover, layers, metric, proximityRule, showcase])

  // render loop: redraw every animation frame; cheap (one recorded frame per draw)
  useEffect(() => {
    let raf = 0
    const loop = () => {
      const video = videoRef.current
      if (video) {
        const t = video.currentTime
        if (pauseOnFire && !video.paused) {
          const crossed = eventsByT.find((e) => lastT.current < e.t && t >= e.t)
          if (crossed) {
            video.pause()
            video.currentTime = crossed.t
          }
        }
        lastT.current = video.currentTime
        setTime((prev) => (Math.abs(prev - video.currentTime) > 0.03 ? video.currentTime : prev))
        onTimeRef.current?.(video.currentTime)
      }
      draw()
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [draw, eventsByT, pauseOnFire])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !seek) return
    video.currentTime = seek.t
    lastT.current = seek.t
    void video.play().catch(() => undefined)
  }, [seek])

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = rate
  }, [rate])

  const onPointerMove = (ev: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    const video = videoRef.current
    if (!canvas || !video) return
    const rect = canvas.getBoundingClientRect()
    const cx = ev.clientX - rect.left
    const cy = ev.clientY - rect.top
    const s = rect.width / showcase.width
    const frame = showcase.frames[frameIndexAt(showcase.frames, video.currentTime)]
    const hit = frame?.tracks
      .filter(
        (tr) =>
          cx >= tr.bbox[0] * s && cx <= tr.bbox[2] * s && cy >= tr.bbox[1] * s && cy <= tr.bbox[3] * s,
      )
      .sort(
        (a, b) =>
          (a.bbox[2] - a.bbox[0]) * (a.bbox[3] - a.bbox[1]) -
          (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1]),
      )[0]
    setHover(hit ? { track: hit, x: cx, y: cy } : null)
  }

  const togglePlay = () => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) void video.play()
    else video.pause()
  }

  const seekTo = (t: number) => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = Math.max(0, Math.min(t, showcase.duration_s - 0.05))
    lastT.current = video.currentTime
  }

  const firedNow = activeEvents(time)

  return (
    <div
      className="flex flex-col gap-2 w-full"
      style={
        maxHeightVh
          ? { maxWidth: `calc(${maxHeightVh}vh * ${showcase.width} / ${showcase.height})` }
          : undefined
      }
    >
      <div
        ref={wrapRef}
        className={`relative w-full rounded-lg overflow-hidden bg-black ring-2 transition-colors ${
          firedNow.length > 0 ? 'ring-red-500' : 'ring-transparent'
        }`}
        style={{ aspectRatio: `${showcase.width} / ${showcase.height}` }}
      >
        <video
          ref={videoRef}
          key={showcase.camera_id}
          src={showcaseVideoUrl(showcase)}
          className="absolute inset-0 w-full h-full"
          muted
          playsInline
          autoPlay={autoPlay}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => {
            // loop manually so the "pause on rule" crossing check re-arms
            lastT.current = 0
            seekTo(0)
            void videoRef.current?.play()
          }}
        />
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full cursor-crosshair"
          onPointerMove={onPointerMove}
          onPointerLeave={() => setHover(null)}
          onClick={togglePlay}
        />
        {hover && (
          <TrackTooltip
            hover={hover}
            metric={metric}
            speed={latestSpeed(showcase, hover.track.id, time)}
            wrap={wrapRef.current}
          />
        )}
        {!playing && (
          <button
            onClick={togglePlay}
            className="absolute bottom-3 right-3 text-xs px-3 py-1.5 rounded-full bg-slate-900/85 text-slate-100 border border-slate-600"
          >
            ▶ Play
          </button>
        )}
      </div>

      <Timeline
        showcase={showcase}
        time={time}
        onSeek={seekTo}
      />

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button
          onClick={togglePlay}
          className="px-3 py-1 rounded-full border border-slate-600 hover:border-slate-400 w-20"
        >
          {playing ? '❚❚ Pause' : '▶ Play'}
        </button>
        <span className="font-mono text-slate-400 w-24">
          {formatClock(time)} / {formatClock(showcase.duration_s)}
        </span>
        <select
          value={rate}
          onChange={(e) => setRate(Number(e.target.value))}
          className="bg-slate-900 border border-slate-700 rounded px-1.5 py-1"
          aria-label="Playback speed"
        >
          <option value={0.25}>0.25×</option>
          <option value={0.5}>0.5×</option>
          <option value={1}>1×</option>
        </select>
        {eventsByT.length > 0 && (
          <button
            onClick={() => {
              seekTo(eventsByT[0].t - 2.5)
              void videoRef.current?.play()
            }}
            className="px-3 py-1 rounded-full border border-red-700 text-red-300 hover:border-red-500"
          >
            Jump to rule firing
          </button>
        )}
        <span className="flex-1" />
        {(Object.keys(DEFAULT_LAYERS) as Array<keyof Layers>)
          .filter((k) => (k === 'distance' ? metric && proximityRule : k === 'zones' ? showcase.zones.length > 0 : true))
          .map((k) => (
            <label key={k} className="flex items-center gap-1 text-slate-300 select-none">
              <input
                type="checkbox"
                checked={layers[k]}
                onChange={(e) => setLayers({ ...layers, [k]: e.target.checked })}
              />
              {k}
            </label>
          ))}
        {eventsByT.length > 0 && (
          <label className="flex items-center gap-1 text-slate-300 select-none">
            <input
              type="checkbox"
              checked={pauseOnFire}
              onChange={(e) => setPauseOnFire(e.target.checked)}
            />
            pause on rule
          </label>
        )}
      </div>
    </div>
  )
}

/** Speed is only measured on the 10 Hz rule-evaluation frames: use the latest one (<= 0.5 s old). */
function latestSpeed(showcase: Showcase, trackId: number, t: number): number | null {
  for (let i = frameIndexAt(showcase.frames, t); i >= 0; i--) {
    const frame = showcase.frames[i]
    if (frame.t < t - 0.5) break
    const speed = frame.tracks.find((tr) => tr.id === trackId)?.speed
    if (speed !== undefined && speed !== null) return speed
  }
  return null
}

function TrackTooltip({
  hover,
  metric,
  speed,
  wrap,
}: {
  hover: Hover
  metric: boolean
  speed: number | null
  wrap: HTMLDivElement | null
}) {
  const { track } = hover
  const width = wrap?.clientWidth ?? 800
  const left = Math.min(hover.x + 14, width - 230)
  return (
    <div
      className="absolute pointer-events-none z-10 w-56 rounded-md bg-slate-950/95 border border-slate-600 p-2 text-xs shadow-lg"
      style={{ left, top: Math.max(8, hover.y - 10) }}
    >
      <div className="font-semibold" style={{ color: classColor(track.cls) }}>
        {CLASS_LABEL[track.cls] ?? track.cls} · track #{track.id}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 mt-1 text-slate-300">
        <dt className="text-slate-500">confidence</dt>
        <dd className="font-mono">{track.conf.toFixed(2)}</dd>
        <dt className="text-slate-500">floor position</dt>
        <dd className="font-mono">
          {track.g ? `x ${track.g[0].toFixed(1)} m, y ${track.g[1].toFixed(1)} m` : 'uncalibrated'}
        </dd>
        <dt className="text-slate-500">speed</dt>
        <dd className="font-mono">
          {speed !== null
            ? `${speed.toFixed(2)} m/s`
            : metric
              ? 'settling…'
              : 'off (zone-only)'}
        </dd>
        <dt className="text-slate-500">zones</dt>
        <dd className="font-mono">{track.zones.length ? track.zones.join(', ') : '—'}</dd>
      </dl>
    </div>
  )
}

function Timeline({
  showcase,
  time,
  onSeek,
}: {
  showcase: Showcase
  time: number
  onSeek: (t: number) => void
}) {
  const barRef = useRef<HTMLDivElement>(null)
  const pct = (t: number) => `${(100 * t) / showcase.duration_s}%`
  const seekFromEvent = (clientX: number) => {
    const bar = barRef.current
    if (!bar) return
    const rect = bar.getBoundingClientRect()
    onSeek(((clientX - rect.left) / rect.width) * showcase.duration_s)
  }
  return (
    <div
      ref={barRef}
      className="relative h-6 rounded bg-slate-800 cursor-pointer"
      onPointerDown={(e) => seekFromEvent(e.clientX)}
      onPointerMove={(e) => e.buttons === 1 && seekFromEvent(e.clientX)}
      role="slider"
      aria-label="Seek"
      aria-valuemin={0}
      aria-valuemax={showcase.duration_s}
      aria-valuenow={time}
    >
      <div className="absolute inset-y-0 left-0 rounded bg-slate-600/70" style={{ width: pct(time) }} />
      {showcase.events.map((e) => (
        <div
          key={e.event_id}
          title={`${e.rule_id} at ${formatClock(e.t)}`}
          className="absolute inset-y-0 w-1 bg-red-500"
          style={{ left: pct(e.t) }}
        />
      ))}
      {showcase.events.map((e) => (
        <span
          key={`${e.event_id}-label`}
          className="absolute -top-0.5 text-[10px] font-semibold text-red-300 pl-1.5 whitespace-nowrap"
          style={{ left: pct(e.t) }}
        >
          rule fired
        </span>
      ))}
      <div className="absolute inset-y-0 w-0.5 bg-white" style={{ left: pct(time) }} />
    </div>
  )
}
