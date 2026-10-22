import { parse } from 'yaml'

import { randInt, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { trials: number; deadline_ms: number; right_within: number }

export interface LineItem {
  target: number
  max: number
}

const NICE = [10, 20, 50, 100, 200, 500, 1000]

export function makeItems(rng: Rng, count: number, rangeMax: number): LineItem[] {
  const max = NICE.find((n) => n >= rangeMax) ?? 1000
  return Array.from({ length: count }, () => ({ target: randInt(rng, 1, max - 1), max }))
}

export function scoreFor(chosen: number, item: LineItem): number {
  return Math.max(0, 1 - Math.abs(chosen - item.target) / item.max)
}

const LinePlugin = makePlugin<LineItem>(
  'lodestar-number-line',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    stage.append(el('div', 'nl-target', String(item.target)))
    const line = el('div', 'nl-line')
    line.dataset['testid'] = 'number-line'
    line.setAttribute('role', 'slider')
    line.setAttribute('aria-label', `Number line from 0 to ${String(item.max)}`)
    line.append(el('span', 'nl-end nl-start', '0'), el('span', 'nl-end nl-stop', String(item.max)))
    stage.append(line)
    const chosen: { value: number | null } = { value: null }
    const response = await waitForResponse(jsPsych, {
      keys: [],
      targets: [{ element: line, key: 'point' }],
      deadlineMs: config.deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, `point:number-line:${(item.target / item.max).toFixed(4)}`)
        line.addEventListener(
          'pointerdown',
          (event) => {
            const box = line.getBoundingClientRect()
            chosen.value = Math.round(((event.clientX - box.left) / box.width) * item.max)
          },
          { capture: true },
        )
      },
    })
    const placed = response.key === null ? null : chosen.value
    const score = placed === null ? 0 : scoreFor(placed, item)
    const correct =
      placed !== null && Math.abs(placed - item.target) / item.max <= config.right_within
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: placed === null ? null : { placed, score },
      correct,
      rt_ms: response.rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice && t.response !== null)
  const errors = scored.map(
    (t) =>
      Math.abs((t.response?.['placed'] as number) - (t.stimulus['target'] as number)) /
      (t.stimulus['max'] as number),
  )
  return {
    mean_abs_error_share: errors.length ? errors.reduce((a, b) => a + b, 0) / errors.length : 1,
    accuracy: trials.filter((t) => !t.practice).length
      ? scored.filter((t) => t.correct === true).length / trials.filter((t) => !t.practice).length
      : 0,
  }
}

export const game: GameModule = {
  id: 'number_line',
  name: 'Number Line',
  instructions:
    'A number appears above a line that runs from 0 to a maximum. Tap where the number belongs on the line.',
  keysHint: 'Tap or click on the line.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['range_max'] ?? 100,
    )
    return itemsToTimeline(LinePlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
