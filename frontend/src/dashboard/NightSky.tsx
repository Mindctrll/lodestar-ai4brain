import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'

import type { DimensionView, Registry } from '../api/types'

/** Where each group of skills starts on the map (docs/plan/13). People can drag skills around;
 * the layout they make is kept on this device. */
const GROUP_CENTRE: Record<string, [number, number]> = {
  attention: [180, 150],
  control: [470, 120],
  memory: [770, 160],
  speed: [780, 420],
  reasoning: [160, 420],
  language: [500, 440],
}
const WIDTH = 900
const HEIGHT = 540
const SAVED = 'lodestar.twin.layout'

type Point = [number, number]

function hash(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619)
  return h >>> 0
}

interface Placed {
  id: string
  name: string
  x: number
  y: number
  view: DimensionView | undefined
  experimental: boolean
}

function place(registry: Registry, dims: DimensionView[], moved: Record<string, Point>): Placed[] {
  const byGroup = new Map<string, Registry['dimensions']>()
  for (const d of registry.dimensions) {
    if (d.style || !(d.group in GROUP_CENTRE)) continue
    byGroup.set(d.group, [...(byGroup.get(d.group) ?? []), d])
  }
  const out: Placed[] = []
  for (const [group, members] of byGroup) {
    const [cx, cy] = GROUP_CENTRE[group] ?? [0, 0]
    members.forEach((d, i) => {
      const angle = (i / members.length) * Math.PI * 2 + (hash(group) % 100) / 50
      const spread = members.length > 1 ? 88 : 0
      const [x, y] = moved[d.id] ?? [
        cx + Math.cos(angle) * spread,
        cy + Math.sin(angle) * spread * 0.7,
      ]
      out.push({
        id: d.id,
        name: d.name,
        x,
        y,
        view: dims.find((v) => v.dim === d.id && v.n > 0),
        experimental: d.badge === 'experimental',
      })
    })
  }
  return out
}

function loadLayout(): Record<string, Point> {
  try {
    const saved = window.localStorage.getItem(SAVED)
    return saved ? (JSON.parse(saved) as Record<string, Point>) : {}
  } catch {
    return {}
  }
}

function saveLayout(layout: Record<string, Point>) {
  try {
    window.localStorage.setItem(SAVED, JSON.stringify(layout))
  } catch {
    // A private window: the layout lasts until the page closes.
  }
}

const pct = (x: number) => `${String(Math.round(x))}%`
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** The Brain Twin as a map of skills. Each measured skill is a node: its size and the number in it
 * are the estimate, the arc around it is the likely range, and the soft glow widens while
 * Lodestar is still unsure. Skills not measured yet are small dots. Lines join skills that tend to
 * go together (NCPT). Nodes can be dragged; a tap opens the skill. */
export function NightSky({
  registry,
  dims,
  onSelect,
  compact = false,
  pulse = 0,
  testId = 'night-sky',
}: {
  registry: Registry
  dims: DimensionView[]
  onSelect?: ((dim: string) => void) | undefined
  compact?: boolean
  pulse?: number
  testId?: string
}) {
  const [layout, setLayout] = useState<Record<string, Point>>(loadLayout)
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<{ id: string; from: Point; offset: Point; moved: boolean } | null>(null)
  const dragged = useRef(false)
  const placed = place(registry, dims, layout)
  const at = new Map(placed.map((p) => [p.id, p]))
  const links = (registry.priors?.correlations ?? []).filter(([, , r]) => r >= 0.4)

  const toMap = (e: PointerEvent): Point | null => {
    const box = svg.current
    const m = box && typeof box.getScreenCTM === 'function' ? box.getScreenCTM() : null
    if (!m) return null
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse())
    return [p.x, p.y]
  }
  const onDown = (e: PointerEvent<SVGGElement>, p: Placed) => {
    const where = toMap(e)
    if (!where || e.button !== 0) return
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { id: p.id, from: where, offset: [p.x - where[0], p.y - where[1]], moved: false }
    dragged.current = false
  }
  const onMove = (e: PointerEvent<SVGGElement>) => {
    const d = drag.current
    const where = d && toMap(e)
    if (!d || !where) return
    if (!d.moved && Math.hypot(where[0] - d.from[0], where[1] - d.from[1]) < 4) return
    d.moved = true
    const x = clamp(where[0] + d.offset[0], 40, WIDTH - 40)
    const y = clamp(where[1] + d.offset[1], 40, HEIGHT - 50)
    setLayout((l) => ({ ...l, [d.id]: [x, y] }))
  }
  const onUp = () => {
    const d = drag.current
    drag.current = null
    if (d?.moved) {
      dragged.current = true
      setLayout((l) => {
        saveLayout(l)
        return l
      })
    }
  }
  const select = (id: string) => {
    if (dragged.current) {
      dragged.current = false
      return
    }
    onSelect?.(id)
  }
  const onKey = (e: KeyboardEvent, id: string) => {
    if (onSelect && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault()
      onSelect(id)
    }
  }

  return (
    <figure className={`twin-map${compact ? ' twin-map--compact' : ''}`} data-testid={testId}>
      <svg
        ref={svg}
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        role="group"
        aria-label="Your Brain Twin: a map of your skills"
        key={pulse}
      >
        <defs>
          <linearGradient id={`${testId}-fill`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#38bdf8" />
            <stop offset="100%" stopColor="#0069a8" />
          </linearGradient>
          {placed.map((p) =>
            p.view ? (
              <filter
                key={p.id}
                id={`${testId}-glow-${p.id}`}
                x="-100%"
                y="-100%"
                width="300%"
                height="300%"
              >
                <feGaussianBlur stdDeviation={Math.max(1, p.view.sigma * 10).toFixed(2)} />
              </filter>
            ) : null,
          )}
        </defs>
        {links.map(([a, b, r]) => {
          const pa = at.get(a)
          const pb = at.get(b)
          if (!pa || !pb) return null
          return (
            <line
              key={`${a}-${b}`}
              className="twin-map__link"
              x1={pa.x}
              y1={pa.y}
              x2={pb.x}
              y2={pb.y}
              strokeOpacity={0.15 + (r - 0.4) * 0.9}
            >
              <title>{`${pa.name} and ${pb.name} tend to go together`}</title>
            </line>
          )
        })}
        {placed.map((p) => {
          const v = p.view
          const label = v
            ? `${p.name}: ${pct(v.percent)}, likely ${pct(v.percent_low)} to ${pct(v.percent_high)}${v.still_learning ? ', still learning about you' : ''}`
            : `${p.name}: not measured yet`
          const radius = v ? (compact ? 14 : 22) + (v.percent / 100) * (compact ? 6 : 12) : 6
          const ring = radius + (compact ? 4 : 7)
          const around = 2 * Math.PI * ring
          return (
            <g
              key={p.id}
              className={`twin-node${v ? '' : ' twin-node--new'}${onSelect ? ' twin-node--link' : ''}`}
              data-dim={p.id}
              data-blur={v ? (v.sigma * 4).toFixed(2) : 'none'}
              role={onSelect ? 'button' : 'img'}
              tabIndex={onSelect ? 0 : undefined}
              aria-label={label}
              onPointerDown={(e) => {
                onDown(e, p)
              }}
              onPointerMove={onMove}
              onPointerUp={onUp}
              onPointerCancel={onUp}
              onClick={() => {
                select(p.id)
              }}
              onKeyDown={(e) => {
                onKey(e, p.id)
              }}
            >
              <title>{label}</title>
              {v ? (
                <>
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={ring}
                    className="twin-node__glow"
                    fill={`url(#${testId}-fill)`}
                    filter={`url(#${testId}-glow-${p.id})`}
                  />
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={ring}
                    className="twin-node__track"
                    strokeDasharray={p.experimental ? '3 4' : undefined}
                  />
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={ring}
                    className="twin-node__range"
                    strokeDasharray={`${String((around * (v.percent_high - v.percent_low)) / 100)} ${String(around)}`}
                    strokeDashoffset={-(around * v.percent_low) / 100}
                    transform={`rotate(-90 ${String(p.x)} ${String(p.y)})`}
                  />
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={radius}
                    className="twin-node__core"
                    fill={`url(#${testId}-fill)`}
                  />
                  <text x={p.x} y={p.y} className="twin-node__value" dy="0.35em">
                    {Math.round(v.percent)}
                  </text>
                </>
              ) : (
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={radius}
                  className="twin-node__dot"
                  strokeDasharray={p.experimental ? '2 2' : undefined}
                />
              )}
              {!compact && (
                <text x={p.x} y={p.y + ring + (v ? 20 : 14)} className="twin-node__name">
                  <tspan x={p.x}>{p.name}</tspan>
                  {v && (
                    <tspan x={p.x} dy="15" className="twin-node__range-text">
                      {`likely ${pct(v.percent_low)}-${pct(v.percent_high)}`}
                    </tspan>
                  )}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      <figcaption className="twin-map__caption">
        Bigger nodes mean a higher estimate; the arc is the likely range and the glow widens while
        Lodestar is unsure. Small dots are skills not measured yet. Drag any skill to move it.
        Dashed: experimental skills. Percentages use simulated norms.
      </figcaption>
    </figure>
  )
}
