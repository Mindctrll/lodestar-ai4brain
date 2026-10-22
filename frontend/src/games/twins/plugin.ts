import { parse } from 'yaml'

import { pick, randInt, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, choose, perMinute } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as {
  trials: number
  deadline_ms: number
  symbols: string
  lookalikes: [string, string][]
}

export interface TwinsItem {
  left: string
  right: string
  same: boolean
  deadline_ms: number
}

/** Pairs of symbol strings (Salthouse's pattern comparison). Complexity makes them longer and
 * makes a difference a look-alike swap instead of any symbol. */
export function makeItems(rng: Rng, count: number, complexity: number): TwinsItem[] {
  const length = 3 + Math.round(6 * complexity)
  return Array.from({ length: count }, () => {
    const left = Array.from({ length }, () => pick(rng, config.symbols.split(''))).join('')
    const same = rng() < 0.5
    let right = left
    if (!same) {
      const at = randInt(rng, 0, length - 1)
      const was = left[at] ?? ''
      const pair = config.lookalikes.find((p) => p.includes(was))
      const swap =
        rng() < complexity && pair
          ? pair[0] === was
            ? pair[1]
            : pair[0]
          : pick(
              rng,
              config.symbols.split('').filter((s) => s !== was),
            )
      right = left.slice(0, at) + swap + left.slice(at + 1)
    }
    return { left, right, same, deadline_ms: config.deadline_ms }
  })
}

const TwinsPlugin = makePlugin<TwinsItem>(
  'lodestar-twins',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const pair = el('div', 'twins-pair')
    pair.append(el('span', 'twins-string', item.left), el('span', 'twins-string', item.right))
    stage.append(pair)
    const { index, rt } = await choose(
      jsPsych,
      stage,
      e2e,
      ['Same (F)', 'Different (J)'],
      item.same ? 0 : 1,
      {
        keys: ['f', 'j'],
        deadlineMs: item.deadline_ms,
      },
    )
    const correct = index === (item.same ? 0 : 1)
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: index === null ? null : { same: index === 0 },
      correct,
      rt_ms: rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  return { items_per_min: perMinute(trials), accuracy: accuracy(trials) }
}

export const game: GameModule = {
  id: 'twins',
  name: 'Twins',
  instructions: 'Are the two rows exactly the same? Answer as fast as you can.',
  keysHint: 'F for same, J for different, or tap the buttons.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['complexity'] ?? 0.4,
    )
    return itemsToTimeline(TwinsPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
