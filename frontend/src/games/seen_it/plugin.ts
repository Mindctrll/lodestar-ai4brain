import { parse } from 'yaml'

import { shuffle, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { dPrime } from '../echo/plugin'
import { choose, scored } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { show_ms: number; categories: Record<string, string[]> }

export type SeenItem =
  | { phase: 'study'; pictures: string[]; show_ms: number }
  | { phase: 'test'; picture: string; old: boolean }

/** A study list, then each studied picture and as many new ones in random order. With high
 * similarity the new pictures come from the studied pictures' own categories. */
export function makeItems(rng: Rng, setSize: number, similarity: number): SeenItem[] {
  const categories = shuffle(rng, Object.values(config.categories))
  const studied =
    categories.length > 1 ? categories.slice(0, Math.ceil(categories.length / 2)) : categories
  const other = categories.slice(studied.length)
  const near = shuffle(rng, studied.flat())
  const old = near.slice(0, setSize)
  const nearNew = near.slice(setSize)
  const farNew = shuffle(rng, other.flat())
  const fresh: string[] = []
  for (let i = 0; i < setSize; i++) {
    const useNear = rng() < similarity && nearNew.length > 0
    const next = (useNear ? nearNew : farNew).shift() ?? nearNew.shift() ?? farNew.shift()
    if (next) fresh.push(next)
  }
  const tests = shuffle(rng, [
    ...old.map((picture) => ({ phase: 'test' as const, picture, old: true })),
    ...fresh.map((picture) => ({ phase: 'test' as const, picture, old: false })),
  ])
  return [{ phase: 'study', pictures: old, show_ms: config.show_ms }, ...tests]
}

const SeenPlugin = makePlugin<SeenItem>(
  'najma-seen-it',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const picture = el('div', 'big-symbol')
    stage.append(picture)
    if (item.phase === 'study') {
      markAnswer(stage, e2e, 'none')
      for (const p of item.pictures) {
        picture.textContent = p
        await wait(item.show_ms)
        picture.textContent = ''
        await wait(200)
      }
      return []
    }
    picture.textContent = item.picture
    const { index, rt } = await choose(
      jsPsych,
      stage,
      e2e,
      ['Seen it (F)', 'New (J)'],
      item.old ? 0 : 1,
      {
        keys: ['f', 'j'],
      },
    )
    const correct = index === (item.old ? 0 : 1)
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { picture: item.picture, old: item.old },
      response: index === null ? null : { said_old: index === 0 },
      correct,
      rt_ms: rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const old = s.filter((t) => t.stimulus['old'] === true)
  const fresh = s.filter((t) => t.stimulus['old'] === false)
  const hits = old.filter((t) => t.correct === true).length
  const falseAlarms = fresh.filter((t) => t.correct === false).length
  return {
    recognition_d_prime: dPrime(hits, old.length - hits, falseAlarms, fresh.length - falseAlarms),
    accuracy: s.length ? s.filter((t) => t.correct === true).length / s.length : 0,
  }
}

export const game: GameModule = {
  id: 'seen_it',
  name: 'Seen It?',
  instructions:
    'First, look at a series of pictures. Then, for each picture, say whether you saw it before or it’s new.',
  keysHint: 'F for seen it, J for new, or tap the buttons.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      Math.round(spec.knobs['set_size'] ?? 12),
      spec.knobs['similarity'] ?? 0.5,
    )
    // The study list is step 0; it has no answers, so practice starts after it.
    return itemsToTimeline(SeenPlugin, items, 0, e2e)
  },
  metrics,
}
