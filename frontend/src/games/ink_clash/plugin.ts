import { parse } from 'yaml'

import { median, pick, shuffle, type Rng } from '../../lib/rng'
import { itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

interface Colour {
  name: string
  hex: string
}
interface Config {
  trials: number
  keys: string[]
  colours: Colour[]
}
const config = parse(rawConfig) as Config
const NAMES = config.colours.map((c) => c.name)

export interface InkItem {
  word: string
  ink: string
  congruent: boolean
  deadline_ms: number
  mapping: string[] // colour name for each key, in key order
}

export function makeItems(
  rng: Rng,
  count: number,
  incongruentRatio: number,
  deadlineMs: number,
  shuffled: boolean,
): InkItem[] {
  const mapping = shuffled ? shuffle(rng, NAMES) : [...NAMES]
  return Array.from({ length: count }, () => {
    const ink = pick(rng, NAMES)
    const congruent = rng() >= incongruentRatio
    const word = congruent
      ? ink
      : pick(
          rng,
          NAMES.filter((n) => n !== ink),
        )
    return { word, ink, congruent, deadline_ms: deadlineMs, mapping }
  })
}

export function keyForInk(item: InkItem): string {
  return config.keys[item.mapping.indexOf(item.ink)] ?? 'd'
}

const hexOf = (name: string) => config.colours.find((c) => c.name === name)?.hex ?? '#000'

const InkClashPlugin = makePlugin<InkItem>(
  'najma-ink-clash',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const word = document.createElement('div')
    word.className = 'ic-word'
    word.textContent = item.word.toUpperCase()
    word.style.color = hexOf(item.ink)
    word.dataset['testid'] = 'ink-word'
    const buttons = item.mapping.map((name, i) => {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = `ic-button pattern-${name}`
      button.dataset['testid'] = `colour-${name}`
      const swatch = document.createElement('span')
      swatch.className = 'ic-swatch'
      swatch.style.background = hexOf(name)
      const label = document.createElement('span')
      label.textContent = `${name} (${(config.keys[i] ?? '').toUpperCase()})`
      button.append(swatch, label)
      return button
    })
    const row = document.createElement('div')
    row.className = 'ic-row'
    row.append(...buttons)
    stage.append(word, row)
    const response = await waitForResponse(jsPsych, {
      keys: config.keys,
      targets: buttons.map((element, i) => ({ element, key: config.keys[i] ?? '' })),
      deadlineMs: item.deadline_ms,
      onReady: () => {
        if (e2e) stage.dataset['answer'] = keyForInk(item)
      },
    })
    const chosen =
      response.key === null ? null : (item.mapping[config.keys.indexOf(response.key)] ?? null)
    const correct = chosen === item.ink
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: {
        word: item.word,
        ink: item.ink,
        congruent: item.congruent,
        deadline_ms: item.deadline_ms,
      },
      response: response.key === null ? null : { key: response.key, colour: chosen },
      correct,
      rt_ms: response.rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  const rtOf = (congruent: boolean) =>
    median(
      scored
        .filter(
          (t) => t.correct === true && t.rt_ms !== null && t.stimulus['congruent'] === congruent,
        )
        .map((t) => t.rt_ms as number),
    )
  const out: Record<string, number> = {
    accuracy: scored.length ? scored.filter((t) => t.correct === true).length / scored.length : 0,
  }
  const matched = rtOf(true)
  const mismatched = rtOf(false)
  if (matched !== null && mismatched !== null) out['stroop_effect_ms'] = mismatched - matched
  return out
}

export const game: GameModule = {
  id: 'ink_clash',
  name: 'Ink Clash',
  instructions:
    'A colour word appears in coloured ink. Answer the colour of the ink, not the word.',
  keysHint: 'D F J K, in the order of the buttons, or tap a button.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['incongruent_ratio'] ?? 0.5,
      spec.knobs['deadline_ms'] ?? 2000,
      (spec.knobs['shuffled_buttons'] ?? 0) >= 0.5,
    )
    return itemsToTimeline(InkClashPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
