import type { Rng } from '../../lib/rng'
import { button, el, markAnswer } from '../../taskhost/plugin'
import { taps } from './ask'

/** Trail Making boards (Reitan, 1958), shared by Connect (part A) and Zigzag (part B). */
export interface TrailBoard {
  labels: string[]
  /** Labels on screen that aren't part of the trail. */
  decoys: string[]
  /** Position of each label, then each decoy, as fractions of the board. */
  spots: [number, number][]
}

export const numbers = (n: number) => Array.from({ length: n }, (_, i) => String(i + 1))

/** 1, A, 2, B, ... */
export function alternating(n: number): string[] {
  return Array.from({ length: n }, (_, i) =>
    i % 2 === 0 ? String(i / 2 + 1) : String.fromCharCode(65 + (i - 1) / 2),
  )
}

/** Spots on a jittered grid, so circles never overlap. */
export function makeBoard(rng: Rng, labels: string[], decoys: string[] = []): TrailBoard {
  const total = labels.length + decoys.length
  const cols = Math.ceil(Math.sqrt(total * 1.5))
  const rows = Math.ceil(total / cols) + 1
  const cells = Array.from({ length: cols * rows }, (_, i) => i)
  for (let i = cells.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1))
    ;[cells[i], cells[j]] = [cells[j] as number, cells[i] as number]
  }
  const spots = cells.slice(0, total).map((c): [number, number] => {
    const x = ((c % cols) + 0.25 + 0.5 * rng()) / cols
    const y = (Math.floor(c / cols) + 0.25 + 0.5 * rng()) / rows
    return [x, y]
  })
  return { labels, decoys, spots }
}

export interface TrailResult {
  time_ms: number
  errors: number
  completed: boolean
}

/** Tap the circles in order; a wrong tap flashes and counts as an error. */
export async function runTrail(
  stage: HTMLElement,
  e2e: boolean,
  board: TrailBoard,
  deadlineMs: number,
): Promise<TrailResult> {
  const area = el('div', 'trail-board')
  const all = [...board.labels, ...board.decoys]
  const dots = all.map((label, i) => {
    const decoy = i >= board.labels.length
    const b = button(label, decoy ? `decoy-${String(i)}` : `dot-${label}`, 'trail-dot')
    const [x, y] = board.spots[i] ?? [0.5, 0.5]
    b.style.left = `${String(x * 100)}%`
    b.style.top = `${String(y * 100)}%`
    return b
  })
  area.append(...dots)
  stage.append(area)
  let next = 0
  let errors = 0
  let time = deadlineMs
  const completed = await taps(
    dots.map((element, i) => ({ element, key: String(i) })),
    {
      deadlineMs,
      onReady: () => {
        markAnswer(stage, e2e, `clicks:${board.labels.map((l) => `dot-${l}`).join('|')}`)
      },
      onTap: (key, ms) => {
        const i = Number(key)
        const dot = dots[i]
        if (!dot || dot.disabled) return false
        if (i !== next) {
          errors += 1
          dot.classList.add('is-wrong')
          window.setTimeout(() => {
            dot.classList.remove('is-wrong')
          }, 300)
          return false
        }
        dot.classList.add('is-done')
        dot.disabled = true
        next += 1
        time = ms
        return next === board.labels.length
      },
    },
  )
  return { time_ms: time, errors, completed }
}

/** Score in [0, 1] for one board: about 0.6 s a circle is full marks, 3 s a circle is none;
 * each wrong tap costs a tenth. */
export function trailScore(result: TrailResult, circles: number): number {
  if (!result.completed) return 0
  const perCircle = result.time_ms / 1000 / circles
  const speed = Math.min(1, Math.max(0, 1 - (perCircle - 0.6) / 2.4))
  return Math.max(0, speed * (1 - 0.1 * result.errors))
}
