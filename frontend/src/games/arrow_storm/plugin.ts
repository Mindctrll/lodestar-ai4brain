import { parse } from 'yaml'

import { median, pick, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

interface Config {
  trials: number
  left_keys: string[]
  right_keys: string[]
}
const config = parse(rawConfig) as Config

export interface ArrowItem {
  target: 'left' | 'right'
  congruent: boolean
  flankers: number
  deadline_ms: number
}

export function makeItems(
  rng: Rng,
  count: number,
  ratio: number,
  flankers: number,
  deadline: number,
): ArrowItem[] {
  return Array.from({ length: count }, () => ({
    target: pick(rng, ['left', 'right'] as const),
    congruent: rng() >= ratio,
    flankers,
    deadline_ms: deadline,
  }))
}

const arrow = (dir: 'left' | 'right') => (dir === 'left' ? '←' : '→')

const ArrowPlugin = makePlugin<ArrowItem>(
  'lodestar-arrow-storm',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const other = item.target === 'left' ? 'right' : 'left'
    const side = Math.max(1, Math.round(item.flankers / 2))
    const flank = arrow(item.congruent ? item.target : other)
    const row = el(
      'div',
      'as-row',
      `${flank.repeat(side)}${arrow(item.target)}${flank.repeat(side)}`,
    )
    row.setAttribute('aria-label', 'Arrows')
    const left = button('← Left', 'arrow-left')
    const right = button('Right →', 'arrow-right')
    const buttons = el('div', 'as-buttons')
    buttons.append(left, right)
    stage.append(row, buttons)
    const response = await waitForResponse(jsPsych, {
      keys: [...config.left_keys, ...config.right_keys],
      targets: [
        { element: left, key: config.left_keys[0] ?? 'arrowleft' },
        { element: right, key: config.right_keys[0] ?? 'arrowright' },
      ],
      deadlineMs: item.deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, item.target === 'left' ? 'key:ArrowLeft' : 'key:ArrowRight')
      },
    })
    const chosen =
      response.key === null ? null : config.left_keys.includes(response.key) ? 'left' : 'right'
    const correct = chosen === item.target
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: chosen === null ? null : { direction: chosen },
      correct,
      rt_ms: response.rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  const rt = (congruent: boolean) =>
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
  const same = rt(true)
  const opposite = rt(false)
  if (same !== null && opposite !== null) out['flanker_cost_ms'] = opposite - same
  return out
}

export const game: GameModule = {
  id: 'arrow_storm',
  name: 'Arrow Storm',
  instructions: 'Which way does the middle arrow point? Ignore the arrows around it.',
  keysHint: 'Left and Right arrow keys, F and J, or tap a button.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['incongruent_ratio'] ?? 0.5,
      Math.round(spec.knobs['flankers'] ?? 2),
      spec.knobs['deadline_ms'] ?? 1500,
    )
    return itemsToTimeline(ArrowPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
