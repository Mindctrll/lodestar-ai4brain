import { parse } from 'yaml'

import { randInt, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, choose, medianRt } from '../shared/ask'
import { node, svg } from '../shared/svg'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as {
  trials: number
  show_ms: number
  deadline_ms: number
  min_dots: number
  max_dots: number
}

export interface JarItem {
  left: number
  right: number
  /** Dot positions per jar, as fractions of the jar, so the picture is part of the seed. */
  dots: [number, number][][]
  deadline_ms: number
}

/** Two dot sets whose smaller-to-larger ratio is the knob (the approximate number system,
 * Halberda et al., 2008). */
export function makeItems(rng: Rng, count: number, ratio: number): JarItem[] {
  return Array.from({ length: count }, () => {
    const big = randInt(rng, Math.ceil(config.min_dots / ratio), config.max_dots)
    const small = Math.max(1, Math.round(big * ratio))
    const leftBigger = rng() < 0.5
    const [left, right] = leftBigger ? [big, small] : [small, big]
    const place = (n: number) =>
      Array.from({ length: n }, (): [number, number] => [0.1 + 0.8 * rng(), 0.1 + 0.8 * rng()])
    return { left, right, dots: [place(left), place(right)], deadline_ms: config.deadline_ms }
  })
}

function jar(dots: [number, number][], label: string): SVGSVGElement {
  const s = svg(100, 100, label)
  s.append(
    node('rect', {
      x: 2,
      y: 2,
      width: 96,
      height: 96,
      rx: 12,
      fill: 'none',
      stroke: 'currentColor',
    }),
  )
  for (const [x, y] of dots)
    s.append(node('circle', { cx: x * 100, cy: y * 100, r: 3, fill: 'currentColor' }))
  return s
}

const JarPlugin = makePlugin<JarItem>(
  'najma-which-jar',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const jars = el('div', 'wj-jars')
    jars.append(jar(item.dots[0] ?? [], 'Left jar'), jar(item.dots[1] ?? [], 'Right jar'))
    stage.append(jars)
    let hide = 0
    const { index, rt } = await choose(
      jsPsych,
      stage,
      e2e,
      ['Left', 'Right'],
      item.left > item.right ? 0 : 1,
      {
        keys: ['arrowleft', 'arrowright'],
        deadlineMs: item.deadline_ms,
        onReady: () => {
          hide = window.setTimeout(() => {
            jars.style.visibility = 'hidden' // too short to count: an estimate, not a tally
          }, config.show_ms)
        },
      },
    )
    window.clearTimeout(hide)
    const correct = index === (item.left > item.right ? 0 : 1)
    if (practice) await practiceFeedback(stage, correct)
    else await wait(200)
    return {
      stimulus: { left: item.left, right: item.right, deadline_ms: item.deadline_ms },
      response: index === null ? null : { side: index === 0 ? 'left' : 'right' },
      correct,
      rt_ms: rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const out: Record<string, number> = { accuracy: accuracy(trials) }
  const rt = medianRt(trials)
  if (rt !== null) out['rt_ms'] = rt
  return out
}

export const game: GameModule = {
  id: 'which_jar',
  name: 'Which Jar?',
  instructions: 'Two jars of dots flash up. Without counting, pick the jar with more dots.',
  keysHint: 'Left and Right arrow keys, or tap the buttons.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(rng, spec.practice_trials + config.trials, spec.knobs['ratio'] ?? 0.7)
    return itemsToTimeline(JarPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
