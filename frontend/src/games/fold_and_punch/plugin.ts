import { parse } from 'yaml'

import { pick, randInt, shuffle, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, medianRt } from '../shared/ask'
import { node, svg } from '../shared/svg'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { trials: number; deadline_ms: number }

/** The paper is a 4 by 4 grid of hole positions. */
const N = 4
type Region = [number, number, number, number] // x0, y0, x1, y1 (end exclusive)
export type Hole = [number, number]

/** `side` is the half that is folded over onto the other half. */
export interface Fold {
  side: 'left' | 'right' | 'top' | 'bottom'
  region: Region
}

export interface FoldItem {
  folds: Fold[]
  punch: Hole
  /** Four hole patterns on the unfolded paper; `answer` is the right one. */
  options: Hole[][]
  answer: number
}

const vertical = (f: Fold) => f.side === 'left' || f.side === 'right'
const line = (f: Fold) => (vertical(f) ? f.region[0] + f.region[2] : f.region[1] + f.region[3]) / 2

/** Mirror a hole across the fold line (or across the other axis, for a wrong option). */
function mirror([x, y]: Hole, f: Fold, swapAxis = false): Hole {
  const v = vertical(f) !== swapAxis
  const l = swapAxis ? N / 2 : line(f)
  return v ? [2 * l - 1 - x, y] : [x, 2 * l - 1 - y]
}

const keyOf = (holes: Hole[]) =>
  holes
    .map(([x, y]) => `${String(x)},${String(y)}`)
    .sort()
    .join(' ')

function unique(holes: Hole[]): Hole[] {
  const seen = new Map(holes.map((h) => [keyOf([h]), h]))
  return [...seen.values()]
}

/** Unfold: every fold, last first, adds the mirror of every hole so far. */
export function unfold(folds: Fold[], punch: Hole, swapAxis = false): Hole[] {
  return folds.reduceRight<Hole[]>(
    (holes, f) => unique([...holes, ...holes.map((h) => mirror(h, f, swapAxis))]),
    [punch],
  )
}

/** What is left of the paper after a fold. */
function after(f: Fold): Region {
  const [x0, y0, x1, y1] = f.region
  const mx = (x0 + x1) / 2
  const my = (y0 + y1) / 2
  if (f.side === 'left') return [mx, y0, x1, y1]
  if (f.side === 'right') return [x0, y0, mx, y1]
  if (f.side === 'top') return [x0, my, x1, y1]
  return [x0, y0, x1, my]
}

export function makeItems(rng: Rng, count: number, folds: number): FoldItem[] {
  return Array.from({ length: count }, () => {
    let region: Region = [0, 0, N, N]
    const list: Fold[] = []
    for (let i = 0; i < folds; i++) {
      const sides = (['left', 'right', 'top', 'bottom'] as const).filter((s) =>
        s === 'left' || s === 'right' ? region[2] - region[0] > 1 : region[3] - region[1] > 1,
      )
      const fold: Fold = { side: pick(rng, sides), region }
      list.push(fold)
      region = after(fold)
    }
    const punch: Hole = [
      randInt(rng, region[0], region[2] - 1),
      randInt(rng, region[1], region[3] - 1),
    ]
    const right = unfold(list, punch)
    const candidates = [[punch], unfold(list, punch, true), unfold(list.slice(1), punch)]
    for (let tries = 0; tries < 40; tries++) {
      const moved = [...right]
      moved[randInt(rng, 0, moved.length - 1)] = [randInt(rng, 0, N - 1), randInt(rng, 0, N - 1)]
      candidates.push(unique(moved))
    }
    const options = [right]
    for (const c of candidates) {
      if (options.length === 4) break
      if (!options.some((o) => keyOf(o) === keyOf(c))) options.push(c)
    }
    const shuffled = shuffle(rng, options)
    return {
      folds: list,
      punch,
      options: shuffled,
      answer: shuffled.findIndex((o) => keyOf(o) === keyOf(right)),
    }
  })
}

const ARROW = { left: '→', right: '←', top: '↓', bottom: '↑' }

/** One step of the folding: the paper so far, with the half that folds over shaded. */
function drawFold(f: Fold): SVGSVGElement {
  const s = svg(N, N, `Fold the ${f.side} half over`)
  const [x0, y0, x1, y1] = f.region
  s.append(node('rect', { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: 'fp-paper' }))
  const half: Region =
    f.side === 'left'
      ? [x0, y0, (x0 + x1) / 2, y1]
      : f.side === 'right'
        ? [(x0 + x1) / 2, y0, x1, y1]
        : f.side === 'top'
          ? [x0, y0, x1, (y0 + y1) / 2]
          : [x0, (y0 + y1) / 2, x1, y1]
  s.append(
    node('rect', {
      x: half[0],
      y: half[1],
      width: half[2] - half[0],
      height: half[3] - half[1],
      class: 'fp-fold',
    }),
  )
  const text = node('text', {
    x: (half[0] + half[2]) / 2,
    y: (half[1] + half[3]) / 2 + 0.25,
    'text-anchor': 'middle',
    'font-size': 0.8,
  })
  text.textContent = ARROW[f.side]
  s.append(text)
  return s
}

function drawPunched(region: Region, punch: Hole): SVGSVGElement {
  const s = svg(N, N, 'The folded paper, punched')
  const [x0, y0, x1, y1] = region
  s.append(node('rect', { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: 'fp-paper' }))
  s.append(node('circle', { cx: punch[0] + 0.5, cy: punch[1] + 0.5, r: 0.25, class: 'fp-hole' }))
  return s
}

function drawHoles(holes: Hole[], label: string): SVGSVGElement {
  const s = svg(N, N, label)
  s.append(node('rect', { x: 0, y: 0, width: N, height: N, class: 'fp-paper' }))
  for (const [x, y] of holes)
    s.append(node('circle', { cx: x + 0.5, cy: y + 0.5, r: 0.25, class: 'fp-hole' }))
  return s
}

const FoldPlugin = makePlugin<FoldItem>(
  'lodestar-fold-and-punch',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const steps = el('div', 'fp-steps')
    steps.append(
      ...item.folds.map(drawFold),
      drawPunched(
        item.folds.reduce<Region>((_, f) => after(f), [0, 0, N, N]),
        item.punch,
      ),
    )
    const row = el('div', 'choice-row')
    const buttons = item.options.map((holes, i) => {
      const b = button('', `choice-${String(i)}`, 'fp-option')
      b.append(drawHoles(holes, `Option ${String(i + 1)}`))
      return b
    })
    row.append(...buttons)
    stage.append(steps, el('p', 'game-prompt', 'Unfolded, where are the holes?'), row)
    const keys = buttons.map((_, i) => String(i + 1))
    const response = await waitForResponse(jsPsych, {
      keys,
      targets: buttons.map((element, i) => ({ element, key: keys[i] ?? '' })),
      deadlineMs: config.deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, `click:choice-${String(item.answer)}`)
      },
    })
    const picked = response.key === null ? null : keys.indexOf(response.key)
    const correct = picked === item.answer
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { folds: item.folds.map((f) => f.side), punch: item.punch, answer: item.answer },
      response: picked === null ? null : { picked },
      correct,
      rt_ms: response.rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const out: Record<string, number> = { accuracy: accuracy(trials) }
  const rt = medianRt(trials)
  if (rt !== null) out['median_rt_ms'] = rt
  return out
}

export const game: GameModule = {
  id: 'fold_and_punch',
  name: 'Fold & Punch',
  instructions:
    'A square of paper is folded (the shaded half folds over), then a hole is punched through every layer. Pick how it looks unfolded.',
  keysHint: 'Tap an option, or press 1 to 4.',
  timeline({ spec, rng, e2e }) {
    const practice = Math.min(2, spec.practice_trials)
    const folds = Math.max(1, Math.min(3, Math.round(spec.knobs['folds'] ?? 2)))
    const items = [...makeItems(rng, practice, 1), ...makeItems(rng, config.trials, folds)]
    return itemsToTimeline(FoldPlugin, items, practice, e2e)
  },
  metrics,
}
