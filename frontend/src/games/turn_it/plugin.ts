import { parse } from 'yaml'

import { pick, randInt, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { node, svg } from '../shared/svg'
import rawConfig from './config.yaml?raw'

interface Config {
  trials: number
  deadline_ms: number
  same_key: string
  mirror_key: string
  shapes: [number, number][][]
}
const config = parse(rawConfig) as Config

export interface TurnItem {
  shape: number
  angle: number
  mirrored: boolean
}

export function makeItems(rng: Rng, count: number, maxAngle: number): TurnItem[] {
  const steps = Math.max(1, Math.round(maxAngle / 45))
  return Array.from({ length: count }, () => ({
    shape: randInt(rng, 0, config.shapes.length - 1),
    angle: 45 * randInt(rng, 0, steps),
    mirrored: pick(rng, [true, false]),
  }))
}

function draw(
  cells: [number, number][],
  angle: number,
  mirrored: boolean,
  label: string,
): SVGSVGElement {
  const s = svg(140, 140, label)
  const g = node('g', {
    transform: `translate(70 70) rotate(${String(angle)}) scale(${String(mirrored ? -1 : 1)} 1) translate(-40 -40)`,
  })
  for (const [c, r] of cells)
    g.append(node('rect', { x: c * 20, y: r * 20, width: 19, height: 19, fill: 'currentColor' }))
  s.append(g)
  return s
}

const TurnPlugin = makePlugin<TurnItem>(
  'lodestar-turn-it',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const cells = config.shapes[item.shape] ?? []
    const pair = el('div', 'ti-pair')
    pair.append(
      draw(cells, 0, false, 'Shape'),
      draw(cells, item.angle, item.mirrored, 'Turned shape'),
    )
    const same = button('Same (F)', 'turn-same')
    const mirror = button('Mirrored (J)', 'turn-mirror')
    const row = el('div', 'ti-buttons')
    row.append(same, mirror)
    stage.append(pair, row)
    const response = await waitForResponse(jsPsych, {
      keys: [config.same_key, config.mirror_key],
      targets: [
        { element: same, key: config.same_key },
        { element: mirror, key: config.mirror_key },
      ],
      deadlineMs: config.deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, `key:${item.mirrored ? config.mirror_key : config.same_key}`)
      },
    })
    const correct = response.key === (item.mirrored ? config.mirror_key : config.same_key)
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: response.key === null ? null : { key: response.key },
      correct,
      rt_ms: response.rt,
    }
  },
)

/** Least-squares slope of RT on angle for correct answers. */
export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  const points = scored
    .filter((t) => t.correct === true && t.rt_ms !== null)
    .map((t) => [t.stimulus['angle'] as number, t.rt_ms as number] as const)
  const out: Record<string, number> = {
    accuracy: scored.length ? scored.filter((t) => t.correct === true).length / scored.length : 0,
  }
  if (points.length >= 3) {
    const mx = points.reduce((s, [x]) => s + x, 0) / points.length
    const my = points.reduce((s, [, y]) => s + y, 0) / points.length
    const sxx = points.reduce((s, [x]) => s + (x - mx) ** 2, 0)
    if (sxx > 0)
      out['angle_rt_slope'] = points.reduce((s, [x, y]) => s + (x - mx) * (y - my), 0) / sxx
  }
  return out
}

export const game: GameModule = {
  id: 'turn_it',
  name: 'Turn It',
  instructions: 'The shape on the right is turned. Is it the same shape, or its mirror image?',
  keysHint: 'F for same, J for mirrored, or tap a button.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['max_angle'] ?? 90,
    )
    return itemsToTimeline(TurnPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
