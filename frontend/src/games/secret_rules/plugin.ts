import { parse } from 'yaml'

import { randInt, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, choose, scored } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as {
  trials: number
  colours: string[]
  shapes: string[]
  frames: string[]
}

/** Card features; each has four values, one per reference card. */
export const FEATURES = ['colour', 'shape', 'count', 'frame'] as const
export type Feature = (typeof FEATURES)[number]
export type Card = Record<Feature, number>

/** The four reference cards are 1 of each value, so any card matches each on one feature. */
export const REFERENCES: Card[] = [0, 1, 2, 3].map((v) => ({
  colour: v,
  shape: v,
  count: v,
  frame: v,
}))

export interface SortItem {
  card: Card
  rules: number
  change_after: number
}

export function makeItems(rng: Rng, count: number, rules: number, changeAfter: number): SortItem[] {
  return Array.from({ length: count }, () => ({
    card: {
      colour: randInt(rng, 0, 3),
      shape: randInt(rng, 0, 3),
      count: randInt(rng, 0, 3),
      frame: randInt(rng, 0, 3),
    },
    rules,
    change_after: changeAfter,
  }))
}

/** The hidden rule (Wisconsin Card Sorting, Berg 1948): it moves to the next feature after
 * `change_after` right answers in a row. Reset at the start of each round. */
export const sorter = { rule: 0, previous: null as number | null, streak: 0 }

export const matchFor = (card: Card, feature: Feature) => card[feature]

function drawCard(card: Card): HTMLElement {
  const box = el('div', `rules-card frame-${config.frames[card.frame] ?? 'solid'}`)
  const symbol = config.shapes[card.shape] ?? '●'
  const shapes = el(
    'span',
    'rules-shapes',
    Array.from({ length: card.count + 1 }, () => symbol).join(' '),
  )
  shapes.style.color = config.colours[card.colour] ?? 'currentColor'
  box.append(shapes)
  return box
}

const SortPlugin = makePlugin<SortItem>(
  'najma-secret-rules',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const feature = FEATURES[sorter.rule % item.rules] ?? 'colour'
    const right = matchFor(item.card, feature)
    const refs = el('div', 'rules-refs')
    refs.append(...REFERENCES.map(drawCard))
    stage.append(
      refs,
      el('p', 'game-prompt', 'Which pile does this card go on?'),
      drawCard(item.card),
    )
    const { index, rt } = await choose(
      jsPsych,
      stage,
      e2e,
      ['Pile 1', 'Pile 2', 'Pile 3', 'Pile 4'],
      right,
      {
        keys: ['1', '2', '3', '4'],
      },
    )
    const correct = index === right
    // A perseverative error follows the rule that just stopped working.
    const previous = sorter.previous === null ? null : FEATURES[sorter.previous % item.rules]
    const perseverative =
      !correct &&
      index !== null &&
      previous !== undefined &&
      previous !== null &&
      matchFor(item.card, previous) === index
    if (!practice) {
      sorter.streak = correct ? sorter.streak + 1 : 0
      if (sorter.streak >= item.change_after) {
        sorter.previous = sorter.rule
        sorter.rule += 1
        sorter.streak = 0
      }
    }
    // Feedback after every card is how the rule is learned.
    stage.append(
      el('div', `najma-feedback ${correct ? 'is-right' : 'is-wrong'}`, correct ? 'Right' : 'Wrong'),
    )
    await wait(600)
    return {
      stimulus: { card: item.card, rule: feature, perseverative },
      response: index === null ? null : { pile: index },
      correct,
      rt_ms: rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  return {
    perseverative_errors: s.filter((t) => t.stimulus['perseverative'] === true).length,
    rule_changes: new Set(s.map((t) => t.stimulus['rule'])).size - 1,
    accuracy: accuracy(trials),
  }
}

export const game: GameModule = {
  id: 'secret_rules',
  name: 'Secret Rules',
  instructions:
    'Put each card on one of the four piles. There’s a secret rule: colour, shape, number or frame. You’ll be told if you’re right, and the rule changes now and then.',
  keysHint: 'Keys 1 to 4, or tap a pile.',
  timeline({ spec, rng, e2e }) {
    Object.assign(sorter, { rule: 0, previous: null, streak: 0 })
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      Math.max(2, Math.min(4, Math.round(spec.knobs['rules'] ?? 2))),
      Math.round(spec.knobs['change_after'] ?? 8),
    )
    return itemsToTimeline(SortPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
