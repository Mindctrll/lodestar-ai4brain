import { parse } from 'yaml'

import { pick, randInt, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, perMinute, typeIn } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { trials: number; deadline_ms: number }

const OPS = ['+', '-', '×', '÷'] as const
type Op = (typeof OPS)[number]

export interface SumItem {
  a: number
  b: number
  op: Op
  answer: number
  deadline_ms: number
}

/** Sums with whole-number answers; `operations` 1 to 4 adds -, × and ÷ in that order. Kept in
 * step with `cli/games.py`, which plays the same sums in the terminal. */
export function makeItems(rng: Rng, count: number, operations: number, max: number): SumItem[] {
  const ops = OPS.slice(0, Math.max(1, Math.min(4, operations)))
  return Array.from({ length: count }, () => {
    const op = pick(rng, ops)
    let a = randInt(rng, 1, max)
    let b = randInt(rng, 1, max)
    if (op === '-' && b > a) [a, b] = [b, a]
    if (op === '×') b = randInt(rng, 1, Math.min(12, max))
    if (op === '÷') {
      b = randInt(rng, 1, Math.min(12, max))
      a = b * randInt(rng, 1, Math.max(1, Math.floor(max / b)))
    }
    const answer = op === '+' ? a + b : op === '-' ? a - b : op === '×' ? a * b : a / b
    return { a, b, op, answer, deadline_ms: config.deadline_ms }
  })
}

const SumPlugin = makePlugin<SumItem>(
  'najma-quick-maths',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    stage.append(el('div', 'big-symbol', `${String(item.a)} ${item.op} ${String(item.b)}`))
    const { text, rt, timedOut } = await typeIn(jsPsych, stage, e2e, String(item.answer), {
      label: 'Answer',
      deadlineMs: item.deadline_ms,
      numeric: true,
    })
    const correct = !timedOut && Number(text) === item.answer && text !== ''
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: text === '' ? null : { typed: text },
      correct,
      rt_ms: timedOut ? null : rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  return { correct_per_min: perMinute(trials), accuracy: accuracy(trials) }
}

export const game: GameModule = {
  id: 'quick_maths',
  name: 'Quick Maths',
  instructions: 'Solve each sum as fast as you can and press Enter.',
  keysHint: 'Type the number, then Enter.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      Math.round(spec.knobs['operations'] ?? 1),
      Math.round(spec.knobs['operand_max'] ?? 10),
    )
    return itemsToTimeline(SumPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
