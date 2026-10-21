import { parse } from 'yaml'

import { pick, shuffle, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { medianRt, scored, typeIn } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as {
  trials: number
  deadline_ms: number
  words: Record<string, string[]>
}

export interface ScrambleItem {
  word: string
  letters: string
  deadline_ms: number
}

export function makeItems(rng: Rng, count: number, length: number): ScrambleItem[] {
  const pool = config.words[String(Math.max(4, Math.min(8, length)))] ?? []
  const words = shuffle(rng, pool)
  return Array.from({ length: count }, (_, i) => {
    const word = words[i % words.length] ?? pick(rng, pool)
    let letters = word
    while (letters === word) letters = shuffle(rng, word.split('')).join('')
    return { word, letters, deadline_ms: config.deadline_ms }
  })
}

const ScramblePlugin = makePlugin<ScrambleItem>(
  'najma-scramble',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    stage.append(
      el('div', 'big-symbol scramble-letters', item.letters.toUpperCase().split('').join(' ')),
    )
    const { text, rt, timedOut } = await typeIn(jsPsych, stage, e2e, item.word, {
      label: 'The word',
      deadlineMs: item.deadline_ms,
    })
    const correct = !timedOut && text.toLowerCase() === item.word
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
  const out: Record<string, number> = {
    solved: scored(trials).filter((t) => t.correct === true).length,
  }
  const rt = medianRt(trials)
  if (rt !== null) out['time_ms'] = rt
  return out
}

export const game: GameModule = {
  id: 'scramble',
  name: 'Scramble',
  instructions: 'The letters of a word are mixed up. Type the word.',
  keysHint: 'Type the word, then Enter.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      Math.round(spec.knobs['length'] ?? 5),
    )
    return itemsToTimeline(ScramblePlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
