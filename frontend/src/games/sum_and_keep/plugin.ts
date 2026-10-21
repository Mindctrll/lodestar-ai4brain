import { parse } from 'yaml'

import { randInt, shuffle, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { choose, nextAnswer, scored, typeIn } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as {
  sets: number
  letters: string
  letter_ms: number
  sum_deadline_ms: number
  min_size: number
  max_size: number
}

export interface Sum {
  text: string
  right: boolean
}

export interface KeepItem {
  /** Enough sums and letters for the largest set; the staircase decides how many are used. */
  sums: Sum[]
  letters: string
}

export function makeItems(rng: Rng, count: number): KeepItem[] {
  return Array.from({ length: count }, () => ({
    sums: Array.from({ length: config.max_size }, () => {
      const a = randInt(rng, 1, 9)
      const b = randInt(rng, 1, 9)
      const right = rng() < 0.5
      const shown = right ? a + b : a + b + (rng() < 0.5 ? -1 : 1) * randInt(rng, 1, 2)
      return { text: `${String(a)} + ${String(b)} = ${String(shown)}`, right }
    }),
    letters: shuffle(rng, config.letters.match(/[A-Z]/g) ?? [])
      .slice(0, config.max_size)
      .join(''),
  }))
}

/** One up, one down within the round, starting at the set-size knob (operation span,
 * Turner & Engle, 1989). */
export const span = { size: 3 }

export const lettersOnly = (typed: string) => typed.toUpperCase().replace(/[^A-Z]/g, '')

const KeepPlugin = makePlugin<KeepItem>(
  'najma-sum-and-keep',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const size = practice ? config.min_size : span.size
    const letters = item.letters.slice(0, size)
    let mathsRight = 0
    for (let k = 0; k < size; k++) {
      const sum = item.sums[k] ?? { text: '', right: true }
      nextAnswer(stage, k)
      stage.replaceChildren(el('div', 'big-symbol', sum.text))
      const { index } = await choose(
        jsPsych,
        stage,
        e2e,
        ['Right (F)', 'Wrong (J)'],
        sum.right ? 0 : 1,
        { keys: ['f', 'j'], deadlineMs: config.sum_deadline_ms },
      )
      if (index === (sum.right ? 0 : 1)) mathsRight += 1
      stage.replaceChildren(el('div', 'big-symbol', letters[k] ?? ''))
      await wait(config.letter_ms)
      stage.replaceChildren()
      await wait(200)
    }
    nextAnswer(stage, size)
    stage.append(el('p', 'game-prompt', 'Which letters did you see, in order?'))
    const { text, rt } = await typeIn(jsPsych, stage, e2e, letters, {
      label: 'Type the letters in order',
      deadlineMs: 30_000,
    })
    const correct = lettersOnly(text) === letters
    if (!practice)
      span.size = Math.max(
        config.min_size,
        Math.min(config.max_size, span.size + (correct ? 1 : -1)),
      )
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { letters, length: size },
      response: { typed: lettersOnly(text), maths_right: mathsRight, maths_total: size },
      correct,
      rt_ms: rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const right = s.filter((t) => t.correct === true)
  const total = s.reduce((n, t) => n + Number(t.response?.['maths_total'] ?? 0), 0)
  const maths = s.reduce((n, t) => n + Number(t.response?.['maths_right'] ?? 0), 0)
  return {
    span: Math.max(0, ...right.map((t) => Number(t.stimulus['length']))),
    maths_accuracy: total ? maths / total : 0,
  }
}

export const game: GameModule = {
  id: 'sum_and_keep',
  name: 'Sum & Keep',
  instructions:
    'Say whether each sum is right or wrong. After each sum a letter shows up: keep the letters in mind, then type them in order.',
  keysHint: 'F for right, J for wrong, or tap. Then type the letters.',
  timeline({ spec, rng, e2e }) {
    span.size = Math.round(spec.knobs['set_size'] ?? 3)
    const practice = Math.min(1, spec.practice_trials)
    return itemsToTimeline(KeepPlugin, makeItems(rng, practice + config.sets), practice, e2e)
  },
  metrics,
}
