import { parse } from 'yaml'

import { randInt, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, scored, typeIn } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { trials: number; min_length: number; max_length: number }

export interface DigitsItem {
  /** Enough digits for the longest list; the staircase decides how many are shown. */
  digits: number[]
  speed_ms: number
}

export function makeItems(rng: Rng, count: number, speed: number): DigitsItem[] {
  return Array.from({ length: count }, () => ({
    digits: Array.from({ length: config.max_length }, () => randInt(rng, 0, 9)),
    speed_ms: speed,
  }))
}

/** One up, one down within the round, starting at the length knob (WAIS-style span). */
export const span = { length: 4 }

export const backwards = (digits: number[]) => [...digits].reverse().join('')
export const digitsOnly = (typed: string) => typed.replace(/\D/g, '')

const DigitsPlugin = makePlugin<DigitsItem>(
  'lodestar-digits-back',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const digits = item.digits.slice(0, span.length)
    const show = el('div', 'big-symbol')
    stage.append(show)
    for (const d of digits) {
      show.textContent = String(d)
      await wait(item.speed_ms * 0.75)
      show.textContent = ''
      await wait(item.speed_ms * 0.25)
    }
    show.remove()
    const { text, rt } = await typeIn(jsPsych, stage, e2e, backwards(digits), {
      label: 'Type the digits backwards',
      deadlineMs: 30_000,
      numeric: true,
      say: { pick: (a) => a.digits.join('') },
    })
    const correct = digitsOnly(text) === backwards(digits)
    if (!practice)
      span.length = Math.max(
        config.min_length,
        Math.min(config.max_length, span.length + (correct ? 1 : -1)),
      )
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { digits, length: digits.length },
      response: { typed: digitsOnly(text) },
      correct,
      rt_ms: rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const right = scored(trials).filter((t) => t.correct === true)
  return {
    span: Math.max(0, ...right.map((t) => Number(t.stimulus['length']))),
    accuracy: accuracy(trials),
  }
}

export const game: GameModule = {
  id: 'digits_back',
  name: 'Digits Back',
  instructions: 'Digits appear one at a time. Then type them in reverse order: 3 8 2 becomes 283.',
  keysHint: 'Type the digits, then Enter.',
  timeline({ spec, rng, e2e }) {
    span.length = Math.round(spec.knobs['length'] ?? 4)
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['speed_ms'] ?? 900,
    )
    return itemsToTimeline(DigitsPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
