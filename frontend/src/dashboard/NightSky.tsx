import type { DimensionView, Registry } from '../api/types'

/** Where each group of skills sits in the sky. Fixed, so people learn the map (docs/plan/13). */
const GROUP_CENTRE: Record<string, [number, number]> = {
  attention: [150, 120],
  control: [330, 250],
  memory: [520, 110],
  speed: [690, 250],
  reasoning: [250, 345],
  language: [600, 350],
}
const WIDTH = 820
const HEIGHT = 430

function hash(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619)
  return h >>> 0
}

function rand(seed: number): () => number {
  let s = seed || 1
  return () => {
    s = Math.imul(s ^ (s >>> 15), 2246822507) ^ Math.imul(s ^ (s >>> 13), 3266489909)
    return ((s ^= s >>> 16) >>> 0) / 4294967296
  }
}

interface Placed {
  id: string
  name: string
  x: number
  y: number
  shape: [number, number][]
  view: DimensionView | undefined
  experimental: boolean
}

function place(registry: Registry, dims: DimensionView[]): Placed[] {
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
      const spread = members.length > 1 ? 62 : 0
      const x = cx + Math.cos(angle) * spread
      const y = cy + Math.sin(angle) * spread * 0.6
      const r = rand(hash(d.id))
      const shape: [number, number][] = Array.from({ length: 3 }, () => [
        x + (r() - 0.5) * 46,
        y + (r() - 0.5) * 34,
      ])
      out.push({
        id: d.id,
        name: d.name,
        x,
        y,
        shape,
        view: dims.find((v) => v.dim === d.id && v.n > 0),
        experimental: d.badge === 'experimental',
      })
    })
  }
  return out
}

const pct = (x: number) => `${String(Math.round(x))}%`

/** The Brain Twin as a night sky: brightness is the estimate, blur is how unsure Najma still is,
 * and lines join skills that tend to go together (NCPT). Stars sharpen as Najma learns. */
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
  const placed = place(registry, dims)
  const at = new Map(placed.map((p) => [p.id, p]))
  const links = (registry.priors?.correlations ?? []).filter(([, , r]) => r >= 0.4)
  const background = Array.from({ length: 70 }, (_, i) => {
    const r = rand(9001 + i)
    return { x: r() * WIDTH, y: r() * HEIGHT, s: r() * 1.1 + 0.2, o: r() * 0.5 + 0.15 }
  })

  return (
    <figure className={`sky${compact ? ' sky--compact' : ''}`} data-testid={testId}>
      <svg
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        role="group"
        aria-label="Your Brain Twin as a night sky"
        key={pulse}
      >
        <defs>
          <radialGradient id={`${testId}-bg`} cx="50%" cy="40%" r="80%">
            <stop offset="0%" stopColor="#1b2350" />
            <stop offset="100%" stopColor="#070a1c" />
          </radialGradient>
          {placed.map((p) => {
            const blur = p.view ? Math.max(0.3, p.view.sigma * 4) : 7
            return (
              <filter
                key={p.id}
                id={`${testId}-blur-${p.id}`}
                x="-200%"
                y="-200%"
                width="500%"
                height="500%"
              >
                <feGaussianBlur stdDeviation={blur.toFixed(2)} />
              </filter>
            )
          })}
        </defs>
        <rect width={WIDTH} height={HEIGHT} fill={`url(#${testId}-bg)`} rx="18" />
        {background.map((b, i) => (
          <circle key={i} cx={b.x} cy={b.y} r={b.s} fill="#fff" opacity={b.o} />
        ))}
        {links.map(([a, b, r]) => {
          const pa = at.get(a)
          const pb = at.get(b)
          if (!pa || !pb) return null
          return (
            <line
              key={`${a}-${b}`}
              x1={pa.x}
              y1={pa.y}
              x2={pb.x}
              y2={pb.y}
              stroke="#8fa6ff"
              strokeOpacity={0.08 + (r - 0.4) * 0.6}
              strokeDasharray="2 6"
            >
              <title>{`${pa.name} and ${pb.name} tend to go together`}</title>
            </line>
          )
        })}
        {placed.map((p) => {
          const v = p.view
          const brightness = v ? 0.35 + (v.percent / 100) * 0.65 : 0.18
          const radius = v ? 3 + (v.percent / 100) * 4 : 2.5
          const label = v
            ? `${p.name}: ${pct(v.percent)}, likely ${pct(v.percent_low)} to ${pct(v.percent_high)}${v.still_learning ? ', still learning about you' : ''}`
            : `${p.name}: not measured yet`
          return (
            <g
              key={p.id}
              className={`constellation${onSelect ? ' constellation--link' : ''}`}
              data-dim={p.id}
              data-blur={v ? (v.sigma * 4).toFixed(2) : 'none'}
              role={onSelect ? 'button' : 'img'}
              tabIndex={onSelect ? 0 : undefined}
              aria-label={label}
              onClick={() => onSelect?.(p.id)}
              onKeyDown={(e) => {
                if (onSelect && (e.key === 'Enter' || e.key === ' ')) {
                  e.preventDefault()
                  onSelect(p.id)
                }
              }}
            >
              <title>{label}</title>
              <polyline
                points={[...p.shape, [p.x, p.y]]
                  .map(([x, y]) => `${String(x)},${String(y)}`)
                  .join(' ')}
                fill="none"
                stroke="#c9d4ff"
                strokeOpacity={v ? 0.35 : 0.12}
                strokeDasharray={p.experimental ? '3 4' : undefined}
              />
              {p.shape.map(([x, y], i) => (
                <circle key={i} cx={x} cy={y} r={1.4} fill="#e6ebff" opacity={brightness * 0.7} />
              ))}
              <circle
                cx={p.x}
                cy={p.y}
                r={radius * 2.4}
                fill="#fff6d8"
                opacity={brightness * 0.55}
                filter={`url(#${testId}-blur-${p.id})`}
              />
              <circle cx={p.x} cy={p.y} r={radius} fill="#fffaf0" opacity={brightness} />
              {!compact && (
                <text x={p.x} y={p.y + 26} textAnchor="middle" className="sky__label">
                  <tspan x={p.x}>{p.name}</tspan>
                  <tspan x={p.x} dy="14" className="sky__value">
                    {v
                      ? `${pct(v.percent)} (${pct(v.percent_low)}-${pct(v.percent_high)})`
                      : 'not measured yet'}
                  </tspan>
                </text>
              )}
            </g>
          )
        })}
      </svg>
      <figcaption className="sky__caption">
        Brighter means a higher estimate; blurrier means Najma is less sure. Dashed: experimental
        skills. Percentages use simulated norms.
      </figcaption>
    </figure>
  )
}
