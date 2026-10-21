import { parse } from 'yaml'

import type { Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { scored, typeIn } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as {
  seconds: number
  full_marks_per_min: number
  /** Letters from easiest to hardest to find words for. */
  letters: string
  examples: Record<string, string[]>
}

export interface BurstItem {
  letter: string
  seconds: number
}

export function makeItems(rng: Rng, difficulty: number): BurstItem[] {
  const n = config.letters.length
  const centre = Math.round(difficulty * (n - 1))
  const i = Math.max(0, Math.min(n - 1, centre + Math.round((rng() - 0.5) * 3)))
  return [{ letter: config.letters[i] ?? 's', seconds: config.seconds }]
}

/** The words that count: start with the letter, at least 3 letters, a vowel, no repeats and no
 * plain plurals of a word already given. There's no dictionary yet, so nonsense that looks like
 * a word would count; the score is low-weight (docs/plan/06). */
export function validWords(typed: string, letter: string): string[] {
  const out: string[] = []
  for (const w of typed.toLowerCase().split(/[^a-z]+/)) {
    if (w.length < 3 || !w.startsWith(letter) || !/[aeiouy]/.test(w)) continue
    if (/(.)\1\1/.test(w)) continue // "sss..." isn't a word
    const stem = w.replace(/e?s$/, '')
    if (out.some((o) => o === w || o.replace(/e?s$/, '') === stem)) continue
    out.push(w)
  }
  return out
}

const BurstPlugin = makePlugin<BurstItem>(
  'najma-word-burst',
  async ({ jsPsych, stage, item, e2e }) => {
    stage.append(el('div', 'big-symbol', item.letter.toUpperCase()))
    const example = (config.examples[item.letter] ?? []).join(' ')
    const { text, rt } = await typeIn(jsPsych, stage, e2e, example, {
      label: `Words starting with ${item.letter.toUpperCase()}`,
      deadlineMs: item.seconds * 1000,
      multiline: true,
      say: { pick: (a) => a.words.join(' '), maxMs: item.seconds * 1000 },
    })
    const words = validWords(text, item.letter)
    const minutes = (rt ?? item.seconds * 1000) / 60_000
    const perMin = words.length / Math.max(minutes, 0.25)
    return {
      stimulus: { letter: item.letter, seconds: item.seconds },
      response: { words, score: Math.min(1, perMin / config.full_marks_per_min) },
      correct: words.length > 0,
      rt_ms: rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const t = scored(trials)[0]
  if (!t) return {}
  const words = (t.response?.['words'] as string[] | undefined) ?? []
  return {
    valid_words: words.length,
    valid_words_per_min: words.length / (Number(t.stimulus['seconds']) / 60),
  }
}

export const game: GameModule = {
  id: 'word_burst',
  name: 'Word Burst',
  instructions:
    'Type as many words as you can that start with the letter, in one minute. No names, and each word once.',
  keysHint: 'Type words separated by spaces; Done ends early.',
  timeline({ spec, rng, e2e }) {
    return itemsToTimeline(
      BurstPlugin,
      makeItems(rng, spec.knobs['letter_difficulty'] ?? 0.3),
      0,
      e2e,
    )
  },
  metrics,
}
