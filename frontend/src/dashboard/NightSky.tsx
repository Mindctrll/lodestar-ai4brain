import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'

import type { DimensionView, Registry } from '../api/types'

/** Each family of skills has a column on the map and a colour (docs/plan/13). People can drag
 * skills around; the layout they make is kept on this device. */
const GROUPS: Record<string, { at: Point; soft: string; strong: string }> = {
  attention: { at: [160, 80], soft: '#e0f2fe', strong: '#0069a8' },
  control: { at: [450, 80], soft: '#ede9fe', strong: '#6d28d9' },
  memory: { at: [740, 80], soft: '#fce7f3', strong: '#be185d' },
  reasoning: { at: [160, 340], soft: '#dcfce7', strong: '#15803d' },
  language: { at: [450, 340], soft: '#ffedd5', strong: '#c2410c' },
  speed: { at: [740, 340], soft: '#fef3c7', strong: '#a16207' },
}
/** Skills a stress case has flagged: a coloured outline and a tag on the card. */
export type SkillMark = 'plateau' | 'advanced' | 'foundation'
const MARK_LABEL: Record<SkillMark, string> = {
  plateau: 'Plateau',
  advanced: '▲ Advanced track',
  foundation: '▼ Foundation track',
}
const WIDTH = 900
const HEIGHT = 560
const ROW = 76
const CARD_H = 58
const SAVED = 'lodestar.twin.layout.v2'

type Point = [number, number]

interface Placed {
  id: string
  name: string
  group: string
  x: number
  y: number
  w: number
  h: number
  view: DimensionView | undefined
  experimental: boolean
}

function place(registry: Registry, dims: DimensionView[], moved: Record<string, Point>): Placed[] {
  const byGroup = new Map<string, Registry['dimensions']>()
  for (const d of registry.dimensions) {
    if (d.style || !(d.group in GROUPS)) continue
    byGroup.set(d.group, [...(byGroup.get(d.group) ?? []), d])
  }
  const out: Placed[] = []
  for (const [group, members] of byGroup) {
    const [cx, cy] = GROUPS[group]?.at ?? [0, 0]
    members.forEach((d, i) => {
      const view = dims.find((v) => v.dim === d.id && v.n > 0)
      const w = view ? Math.max(156, d.name.length * 7.6 + 70) : d.name.length * 6.4 + 34
      const h = view ? CARD_H : 26
      const [x, y] = moved[d.id] ?? [cx + (i % 2 ? 34 : -34), cy + i * ROW]
      out.push({
        id: d.id,
        name: d.name,
        group,
        x,
        y,
        w,
        h,
        view,
        experimental: d.badge === 'experimental',
      })
    })
  }
  return out
}

/** A smooth connector between two node centres, bending like a flow chart's wires. */
function wire(a: Placed, b: Placed): string {
  const midY = (a.y + b.y) / 2
  const xs = (n: number) => String(Math.round(n))
  return `M${xs(a.x)} ${xs(a.y)} C${xs(a.x)} ${xs(midY)}, ${xs(b.x)} ${xs(midY)}, ${xs(b.x)} ${xs(b.y)}`
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

/** The Brain Twin as a map of skills. Each measured skill is a card: the number is the estimate,
 * the bar along its foot is the likely range with the estimate marked, and the soft shadow behind
 * it widens while Lodestar is still unsure. Skills not measured yet are small grey tags. Wires join
 * skills of one family, and blue wires join skills that tend to go together (NCPT). Cards can be
 * dragged; a tap opens the skill. */
export function NightSky({
  marks,
  registry,
  dims,
  onSelect,
  compact = false,
  pulse = 0,
  testId = 'night-sky',
}: {
  /** Skills a stress case has flagged. */
  marks?: Record<string, SkillMark> | undefined
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
  // Each skill's two strongest links to other families, so every skill is wired in and the map
  // stays readable.
  const pairs = (registry.priors?.correlations ?? []).filter(
    ([a, b, r]) => r >= 0.2 && at.has(a) && at.has(b) && at.get(a)?.group !== at.get(b)?.group,
  )
  const keep = new Set<string>()
  for (const p of placed) {
    pairs
      .filter(([a, b]) => a === p.id || b === p.id)
      .sort((x, y) => y[2] - x[2])
      .slice(0, 2)
      .forEach(([a, b]) => keep.add(`${a}|${b}`))
  }
  const related = pairs.filter(([a, b]) => keep.has(`${a}|${b}`))
  const family = placed.flatMap((a, i) =>
    placed.slice(i + 1).flatMap((b) => (a.group === b.group ? [[a, b] as const] : [])),
  )

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
    const p = d && at.get(d.id)
    if (!d || !where || !p) return
    if (!d.moved && Math.hypot(where[0] - d.from[0], where[1] - d.from[1]) < 4) return
    d.moved = true
    const x = clamp(where[0] + d.offset[0], p.w / 2 + 4, WIDTH - p.w / 2 - 4)
    const y = clamp(where[1] + d.offset[1], p.h / 2 + 4, HEIGHT - p.h / 2 - 4)
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
          {placed.map((p) =>
            p.view ? (
              <filter
                key={p.id}
                id={`${testId}-haze-${p.id}`}
                x="-50%"
                y="-100%"
                width="200%"
                height="300%"
              >
                <feGaussianBlur stdDeviation={Math.max(2, p.view.sigma * 12).toFixed(2)} />
              </filter>
            ) : null,
          )}
        </defs>
        {family.map(([a, b]) => (
          <path key={`${a.id}-${b.id}`} d={wire(a, b)} className="twin-wire" />
        ))}
        {related.map(([a, b, r]) => {
          const pa = at.get(a)
          const pb = at.get(b)
          if (!pa || !pb) return null
          return (
            <path
              key={`${a}-${b}`}
              d={wire(pa, pb)}
              className="twin-wire twin-wire--related"
              strokeWidth={1 + r * 2.5}
              strokeOpacity={0.3 + r * 0.6}
            >
              <title>{`${pa.name} and ${pb.name} tend to go together`}</title>
            </path>
          )
        })}
        {placed.map((p) => {
          const v = p.view
          const colour = GROUPS[p.group] ?? { soft: '#f1f5f9', strong: '#314158' }
          const label = v
            ? `${p.name}: ${pct(v.percent)}, likely ${pct(v.percent_low)} to ${pct(v.percent_high)}${v.still_learning ? ', still learning about you' : ''}`
            : `${p.name}: not measured yet`
          const left = p.x - p.w / 2
          const top = p.y - p.h / 2
          const bar = p.w - 24
          return (
            <g
              key={p.id}
              className={`twin-node${v ? '' : ' twin-node--new'}${marks?.[p.id] ? ` twin-node--${String(marks[p.id])}` : ''}`}
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
                  <rect
                    x={left + 6}
                    y={top + 8}
                    width={p.w - 12}
                    height={p.h - 4}
                    rx="14"
                    fill={colour.strong}
                    className="twin-node__haze"
                    filter={`url(#${testId}-haze-${p.id})`}
                  />
                  <rect
                    x={left}
                    y={top}
                    width={p.w}
                    height={p.h}
                    rx="14"
                    className="twin-node__card"
                    strokeDasharray={p.experimental ? '4 4' : undefined}
                  />
                  <rect
                    x={left + 10}
                    y={top + 10}
                    width="34"
                    height="30"
                    rx="9"
                    fill={colour.soft}
                  />
                  <text
                    x={left + 27}
                    y={top + 25}
                    dy="0.35em"
                    className="twin-node__value"
                    fill={colour.strong}
                  >
                    {Math.round(v.percent)}
                  </text>
                  <text x={left + 54} y={top + 22} className="twin-node__name">
                    {p.name}
                  </text>
                  <text x={left + 54} y={top + 38} className="twin-node__range-text">
                    {`likely ${pct(v.percent_low)}-${pct(v.percent_high)}`}
                  </text>
                  {marks?.[p.id] && (
                    <text
                      x={left + p.w - 8}
                      y={top - 5}
                      textAnchor="end"
                      className="twin-node__mark"
                    >
                      {MARK_LABEL[marks[p.id] ?? 'plateau']}
                    </text>
                  )}
                  <rect
                    x={left + 12}
                    y={top + p.h - 9}
                    width={bar}
                    height="3"
                    rx="1.5"
                    className="twin-node__track"
                  />
                  <rect
                    x={left + 12 + (bar * v.percent_low) / 100}
                    y={top + p.h - 9}
                    width={(bar * (v.percent_high - v.percent_low)) / 100}
                    height="3"
                    rx="1.5"
                    fill={colour.strong}
                    opacity="0.35"
                  />
                  <circle
                    cx={left + 12 + (bar * v.percent) / 100}
                    cy={top + p.h - 7.5}
                    r="3"
                    fill={colour.strong}
                  />
                </>
              ) : (
                <>
                  <rect
                    x={left}
                    y={top}
                    width={p.w}
                    height={p.h}
                    rx={p.h / 2}
                    className="twin-node__tag"
                  />
                  <circle cx={left + 13} cy={p.y} r="3" className="twin-node__tag-dot" />
                  <text x={left + 22} y={p.y} dy="0.35em" className="twin-node__tag-name">
                    {p.name}
                  </text>
                </>
              )}
            </g>
          )
        })}
      </svg>
      <figcaption className="twin-map__caption">
        The number is Lodestar&apos;s estimate and the bar under it the likely range; the softer the
        shadow, the less sure Lodestar is. Grey tags are skills not measured yet. Blue wires join
        skills that tend to go together. Drag any skill to move it. Dashed: experimental skills.
        Percentages use simulated norms.
      </figcaption>
    </figure>
  )
}
