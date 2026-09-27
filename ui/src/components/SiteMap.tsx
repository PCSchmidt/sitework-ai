import { useMemo } from 'react'
import {
  classColor,
  closestPair,
  frameIndexAt,
  type Point,
  type Showcase,
} from '../showcase/model'

const TRAIL_S = 3.0

/**
 * Bird's-eye view of the calibrated floor: zones and tracks in meters, camera at the
 * origin looking "up" the page (+y = away from the camera). Everything comes from the
 * recorded ground points -- this is the calibration made visible.
 */
export function SiteMap({ showcase, time }: { showcase: Showcase; time: number }) {
  const bounds = useMemo(() => {
    const xs: number[] = [0]
    const ys: number[] = [0]
    for (const z of showcase.zones)
      for (const [x, y] of z.polygon_m) {
        xs.push(x)
        ys.push(y)
      }
    // Frame the zones; only fall back to track positions when there are none. Points
    // off the floor (a seated driver, a head) project absurdly far and would squash the map.
    if (showcase.zones.length === 0)
      for (const f of showcase.frames)
        for (const tr of f.tracks)
          if (tr.g && Math.abs(tr.g[0]) < 50 && tr.g[1] > 0 && tr.g[1] < 50) {
            xs.push(tr.g[0])
            ys.push(tr.g[1])
          }
    const pad = 1.5
    return {
      minX: Math.min(...xs) - pad,
      maxX: Math.max(...xs) + pad,
      minY: Math.min(...ys) - pad,
      maxY: Math.max(...ys) + pad,
    }
  }, [showcase])

  if (!showcase.calibration) {
    return (
      <div className="h-full min-h-40 flex items-center justify-center rounded-lg border border-dashed border-slate-700 p-4 text-center text-xs text-slate-500">
        No calibration for this camera, so there is no floor plan: positions exist only in
        pixels.
      </div>
    )
  }

  const w = bounds.maxX - bounds.minX
  const h = bounds.maxY - bounds.minY
  // SVG y grows downward; flip so +y (away from camera) points up the page
  const P = ([x, y]: Point): Point => [x - bounds.minX, bounds.maxY - y]
  const step = h > 20 ? 5 : h > 8 ? 2 : 1
  const idx = frameIndexAt(showcase.frames, time)
  const frame = showcase.frames[idx]
  const visible = (g: Point | null): g is Point =>
    !!g && g[0] >= bounds.minX && g[0] <= bounds.maxX && g[1] >= bounds.minY && g[1] <= bounds.maxY
  const trails = new Map<number, Point[]>()
  for (let i = idx; i >= 0 && showcase.frames[i].t >= time - TRAIL_S; i -= 2) {
    for (const tr of showcase.frames[i].tracks) {
      if (!visible(tr.g)) continue
      const list = trails.get(tr.id) ?? []
      list.push(P(tr.g))
      trails.set(tr.id, list)
    }
  }
  const rule = showcase.rules.find((r) => r.kind === 'proximity')
  const pair = rule && showcase.calibration.valid ? closestPair(frame, rule.zone_ids) : null
  const occupied = new Set(frame.tracks.flatMap((tr) => tr.zones))
  const gridX: number[] = []
  for (let x = Math.ceil(bounds.minX / step) * step; x <= bounds.maxX; x += step) gridX.push(x)
  const gridY: number[] = []
  for (let y = Math.ceil(bounds.minY / step) * step; y <= bounds.maxY; y += step) gridY.push(y)
  const font = Math.max(w, h) / 32

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="w-full h-full max-h-[420px] rounded-lg bg-slate-950 border border-slate-800"
      role="img"
      aria-label="Top-down floor plan with tracked objects in meters"
    >
      {gridX.map((x) => (
        <line key={`gx${x}`} x1={x - bounds.minX} x2={x - bounds.minX} y1={0} y2={h} stroke="#1e293b" strokeWidth={0.04} />
      ))}
      {gridY.map((y) => (
        <g key={`gy${y}`}>
          <line x1={0} x2={w} y1={bounds.maxY - y} y2={bounds.maxY - y} stroke="#1e293b" strokeWidth={0.04} />
          <text x={0.2} y={bounds.maxY - y - 0.15} fontSize={font * 0.8} fill="#475569">
            {y} m
          </text>
        </g>
      ))}
      {showcase.zones.map((z) => (
        <g key={z.id}>
          <polygon
            points={z.polygon_m.map((p) => P(p).join(',')).join(' ')}
            fill={occupied.has(z.id) ? 'rgba(250,204,21,0.14)' : 'rgba(56,189,248,0.08)'}
            stroke={occupied.has(z.id) ? '#facc15' : '#38bdf8'}
            strokeWidth={0.08}
            strokeDasharray="0.4 0.3"
          />
          <text
            x={P(z.polygon_m[3] ?? z.polygon_m[0])[0] + 0.3}
            y={P(z.polygon_m[3] ?? z.polygon_m[0])[1] + font * 1.1}
            fontSize={font}
            fill="#7dd3fc"
          >
            {z.id}
          </text>
        </g>
      ))}
      {/* camera at the origin */}
      <g transform={`translate(${P([0, 0]).join(',')})`}>
        <polygon points={`0,0 ${-font * 0.7},${font * 1.2} ${font * 0.7},${font * 1.2}`} fill="#94a3b8" transform="rotate(180)" />
        <text x={font * 0.9} y={font * 0.4} fontSize={font * 0.85} fill="#94a3b8">
          camera
        </text>
      </g>
      {rule && pair && (
        <g>
          <circle
            cx={P(pair.vehicle.g!)[0]}
            cy={P(pair.vehicle.g!)[1]}
            r={rule.radius_m ?? 0}
            fill="none"
            stroke={pair.distance < (rule.radius_m ?? 0) ? '#ef4444' : '#64748b'}
            strokeWidth={0.06}
            strokeDasharray="0.3 0.25"
          />
          <line
            x1={P(pair.person.g!)[0]}
            y1={P(pair.person.g!)[1]}
            x2={P(pair.vehicle.g!)[0]}
            y2={P(pair.vehicle.g!)[1]}
            stroke={pair.distance < (rule.radius_m ?? 0) ? '#ef4444' : '#e2e8f0'}
            strokeWidth={0.07}
          />
          <text
            x={(P(pair.person.g!)[0] + P(pair.vehicle.g!)[0]) / 2}
            y={(P(pair.person.g!)[1] + P(pair.vehicle.g!)[1]) / 2 - 0.3}
            fontSize={font}
            fill="#f8fafc"
            textAnchor="middle"
          >
            {pair.distance.toFixed(1)} m
          </text>
        </g>
      )}
      {[...trails.entries()].map(([id, pts]) => {
        const tr = frame.tracks.find((t) => t.id === id)
        if (!tr || pts.length < 2) return null
        return (
          <polyline
            key={`trail${id}`}
            points={pts.map((p) => p.join(',')).join(' ')}
            fill="none"
            stroke={classColor(tr.cls)}
            strokeOpacity={0.45}
            strokeWidth={0.1}
          />
        )
      })}
      {frame.tracks.filter((tr) => visible(tr.g)).map((tr) => {
        const [x, y] = P(tr.g!)
        return (
          <g key={tr.id}>
            <circle cx={x} cy={y} r={font * 0.45} fill={classColor(tr.cls)} stroke="#0f172a" strokeWidth={0.05} />
            <text x={x + font * 0.6} y={y + font * 0.35} fontSize={font * 0.85} fill="#e2e8f0">
              #{tr.id}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
