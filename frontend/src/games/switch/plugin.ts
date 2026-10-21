import { parse } from 'yaml'

import { median, pick, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, wait, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

interface Config {
  trials: number
  deadline_ms: number
  left_key: string
  right_key: string
  colours: { name: string; hex: string }[]
  shapes: string[]
}
const config = parse(rawConfig) as Config

export interface SwitchItem {
  rule: 'colour' | 'shape'
  colour: number // 0 left, 1 right
  shape: number
  switched: boolean
  cue_ms: number
}

export function makeItems(
  rng: Rng,
  count: number,
  switchRate: number,
  cueMs: number,
): SwitchItem[] {
  const items: SwitchItem[] = []
  let rule: 'colour' | 'shape' = pick(rng, ['colour', 'shape'] as const)
  for (let i = 0; i < count; i++) {
    const switched = i > 0 && rng() < switchRate
    if (switched) rule = rule === 'colour' ? 'shape' : 'colour'
    items.push({
      rule,
      colour: pick(rng, [0, 1]),
      shape: pick(rng, [0, 1]),
      switched,
      cue_ms: cueMs,
    })
  }
  return items
}

export const expectedKey = (item: SwitchItem) =>
  (item.rule === 'colour' ? item.colour : item.shape) === 0 ? config.left_key : config.right_key

const SwitchPlugin = makePlugin<SwitchItem>(
  'najma-switch',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const cue = el('div', 'sw-cue', item.rule === 'colour' ? 'COLOUR' : 'SHAPE')
    stage.append(cue)
    await wait(item.cue_ms)
    const colour = config.colours[item.colour] ?? { name: 'blue', hex: '#1d4ed8' }
    const shapeName = config.shapes[item.shape] ?? 'circle'
    const shape = el('div', `sw-shape sw-${shapeName} pattern-${colour.name}`)
    shape.style.background = colour.hex
    shape.setAttribute('aria-label', `${colour.name} ${shapeName}`)
    const left = button(`F: blue / circle`, 'switch-left')
    const right = button(`J: orange / square`, 'switch-right')
    const row = el('div', 'sw-buttons')
    row.append(left, right)
    stage.append(shape, row)
    const response = await waitForResponse(jsPsych, {
      keys: [config.left_key, config.right_key],
      targets: [
        { element: left, key: config.left_key },
        { element: right, key: config.right_key },
      ],
      deadlineMs: config.deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, `key:${expectedKey(item)}`)
      },
    })
    const correct = response.key === expectedKey(item)
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: response.key === null ? null : { key: response.key },
      correct,
      rt_ms: response.rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  const rt = (switched: boolean) =>
    median(
      scored
        .filter(
          (t) => t.correct === true && t.rt_ms !== null && t.stimulus['switched'] === switched,
        )
        .map((t) => t.rt_ms as number),
    )
  const out: Record<string, number> = {
    accuracy: scored.length ? scored.filter((t) => t.correct === true).length / scored.length : 0,
  }
  const repeat = rt(false)
  const sw = rt(true)
  if (repeat !== null && sw !== null) out['switch_cost_ms'] = sw - repeat
  return out
}

export const game: GameModule = {
  id: 'switch',
  name: 'Switch',
  instructions:
    'The cue tells you how to sort the next shape: by COLOUR (blue F, orange J) or by SHAPE (circle F, square J).',
  keysHint: 'F and J, or tap a button.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['switch_rate'] ?? 0.3,
      spec.knobs['cue_time_ms'] ?? 600,
    )
    return itemsToTimeline(SwitchPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
