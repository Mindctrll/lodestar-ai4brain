import { parse } from 'yaml'

import { shuffle, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { scored, typeIn } from '../shared/ask'
import rawConfig from './config.yaml?raw'

interface Thing {
  id: string
  name: string
  /** Words that mark the everyday uses: ideas using them aren't counted as original. */
  common: string[]
  /** Unusual uses, for end-to-end tests. */
  examples: string[]
}

const config = parse(rawConfig) as {
  objects_per_round: number
  seconds: number
  enough: number
  pass: number
  objects: Thing[]
}

export interface UsesItem {
  thing: Thing
  seconds: number
}

export function makeItems(rng: Rng, count: number): UsesItem[] {
  return shuffle(rng, config.objects)
    .slice(0, count)
    .map((thing) => ({ thing, seconds: config.seconds }))
}

const words = (text: string) => text.toLowerCase().match(/[a-z]+/g) ?? []

/** Scored in code (Alternative Uses Task, Guilford, 1967): fluency is the number of different
 * ideas; an idea is original when it uses none of the object's everyday-use words. The plan's
 * AI rating of originality can replace this later; creativity is experimental and never in an
 * overall score. */
export function rate(
  text: string,
  thing: Thing,
): { ideas: string[]; fluency: number; originality: number; score: number } {
  const seen = new Set<string>()
  const ideas = text
    .split(/[\n,;]+/)
    .map((idea) => idea.trim())
    .filter((idea) => {
      const key = words(idea).join(' ')
      if (!words(idea).some((w) => w.length >= 3) || seen.has(key)) return false
      seen.add(key)
      return true
    })
  const common = new Set(thing.common)
  const originality = ideas.filter((idea) => !words(idea).some((w) => common.has(w))).length
  const score = Math.min(1, (ideas.length + originality) / config.enough)
  return { ideas, fluency: ideas.length, originality, score }
}

const UsesPlugin = makePlugin<UsesItem>(
  'najma-unusual-uses',
  async ({ jsPsych, stage, item, e2e }) => {
    stage.append(
      el('p', 'game-prompt', `How many different uses can you think of for ${item.thing.name}?`),
      el(
        'p',
        'gr-reply',
        'One idea per line (or separate them with commas). Unusual ideas are welcome!',
      ),
    )
    const { text, rt } = await typeIn(jsPsych, stage, e2e, item.thing.examples.join(', '), {
      label: 'Your ideas',
      deadlineMs: item.seconds * 1000,
      multiline: true,
    })
    const { ideas, fluency, originality, score } = rate(text, item.thing)
    stage.replaceChildren(
      el(
        'p',
        'game-prompt',
        `${String(fluency)} ${fluency === 1 ? 'idea' : 'ideas'}. Nice thinking!`,
      ),
    )
    await wait(800)
    return {
      stimulus: { object: item.thing.id },
      response: { ideas, fluency, originality, score },
      correct: score >= config.pass,
      rt_ms: rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const mean = (field: string) =>
    s.length ? s.reduce((n, t) => n + Number(t.response?.[field] ?? 0), 0) / s.length : 0
  return { fluency: mean('fluency'), originality: mean('originality') }
}

export const game: GameModule = {
  id: 'unusual_uses',
  name: 'Unusual Uses',
  instructions:
    'You’ll see an everyday object. List as many different uses for it as you can, the more unusual the better.',
  keysHint: 'Type your ideas, then Done.',
  timeline({ rng, e2e }) {
    return itemsToTimeline(UsesPlugin, makeItems(rng, config.objects_per_round), 0, e2e)
  },
  metrics,
}
