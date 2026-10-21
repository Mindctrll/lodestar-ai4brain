/** Small SVG drawing helpers shared by the shape-based games. */
const NS = 'http://www.w3.org/2000/svg'

export function svg(width: number, height: number, label: string): SVGSVGElement {
  const s = document.createElementNS(NS, 'svg')
  s.setAttribute('viewBox', `0 0 ${String(width)} ${String(height)}`)
  s.setAttribute('role', 'img')
  s.setAttribute('aria-label', label)
  return s
}

export function node<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | number>,
): SVGElementTagNameMap[K] {
  const n = document.createElementNS(NS, tag)
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v))
  return n
}

export interface CellSpec {
  shape: 'circle' | 'square' | 'triangle' | 'diamond' | 'star'
  count: number
  fill: 'empty' | 'striped' | 'solid'
  rotation: number
}

function outline(shape: CellSpec['shape'], r: number): string {
  const pts = (n: number, start: number, radius = r) =>
    Array.from({ length: n }, (_, i) => {
      const a = start + (i * 2 * Math.PI) / n
      return `${(radius * Math.cos(a)).toFixed(1)},${(radius * Math.sin(a)).toFixed(1)}`
    }).join(' ')
  if (shape === 'square') return pts(4, Math.PI / 4)
  if (shape === 'diamond') return pts(4, 0)
  if (shape === 'triangle') return pts(3, -Math.PI / 2)
  if (shape === 'star')
    return Array.from({ length: 10 }, (_, i) => {
      const a = -Math.PI / 2 + (i * Math.PI) / 5
      const rr = i % 2 === 0 ? r : r * 0.45
      return `${(rr * Math.cos(a)).toFixed(1)},${(rr * Math.sin(a)).toFixed(1)}`
    }).join(' ')
  return ''
}

/** One matrix cell: `count` shapes with a fill and a rotation. A small tick marks "up", so the
 * rotation is visible even on symmetric shapes. */
export function drawCell(cell: CellSpec, size = 90): SVGSVGElement {
  const s = svg(
    size,
    size,
    `${String(cell.count)} ${cell.fill} ${cell.shape}, turned ${String(cell.rotation)} degrees`,
  )
  const defs = node('defs', {})
  const id = `stripes-${Math.random().toString(36).slice(2, 8)}`
  const pattern = node('pattern', {
    id,
    width: 6,
    height: 6,
    patternUnits: 'userSpaceOnUse',
    patternTransform: 'rotate(45)',
  })
  pattern.append(
    node('line', { x1: 0, y1: 0, x2: 0, y2: 6, stroke: 'currentColor', 'stroke-width': 2 }),
  )
  defs.append(pattern)
  s.append(defs)
  const fill =
    cell.fill === 'solid' ? 'currentColor' : cell.fill === 'striped' ? `url(#${id})` : 'none'
  const r = cell.count === 1 ? 26 : cell.count === 2 ? 18 : 14
  const xs = cell.count === 1 ? [45] : cell.count === 2 ? [27, 63] : [20, 45, 70]
  for (const x of xs) {
    const g = node('g', {
      transform: `translate(${String(x)} 45) rotate(${String(cell.rotation)})`,
    })
    const style = { fill, stroke: 'currentColor', 'stroke-width': 2.5 }
    g.append(
      cell.shape === 'circle'
        ? node('circle', { r, ...style })
        : node('polygon', { points: outline(cell.shape, r), ...style }),
    )
    g.append(
      node('line', {
        x1: 0,
        y1: -r - 2,
        x2: 0,
        y2: -r - 8,
        stroke: 'currentColor',
        'stroke-width': 2.5,
      }),
    )
    s.append(g)
  }
  return s
}
