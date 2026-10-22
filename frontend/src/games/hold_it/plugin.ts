import { parse } from 'yaml'

import { median, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, wait, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

interface Config {
  trials: number
  go_key: string
}
const config = parse(rawConfig) as Config

export interface HoldItem {
  go: boolean
  window_ms: number
}

export function makeItems(rng: Rng, count: number, goRatio: number, windowMs: number): HoldItem[] {
  return Array.from({ length: count }, () => ({ go: rng() < goRatio, window_ms: windowMs }))
}

const HoldPlugin = makePlugin<HoldItem>(
  'lodestar-hold-it',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const shape = el('div', item.go ? 'hi-shape hi-go' : 'hi-shape hi-hold', item.go ? '' : 'Hold')
    shape.setAttribute('aria-label', item.go ? 'Circle: press' : 'Hold shape: do not press')
    const go = button('Go (Space)', 'go')
    stage.append(shape, go)
    const started = performance.now()
    const response = await waitForResponse(jsPsych, {
      keys: [config.go_key],
      targets: [{ element: go, key: config.go_key }],
      deadlineMs: item.window_ms,
      onReady: () => {
        markAnswer(stage, e2e, item.go ? 'key:Space' : 'none')
      },
    })
    const pressed = response.key !== null
    const correct = pressed === item.go
    if (practice) await practiceFeedback(stage, correct)
    await wait(Math.max(0, item.window_ms - (performance.now() - started)))
    return {
      stimulus: { ...item },
      response: pressed ? { pressed: true } : null,
      correct,
      rt_ms: response.rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  const holds = scored.filter((t) => t.stimulus['go'] === false)
  const goRts = scored
    .filter((t) => t.stimulus['go'] === true && t.correct === true && t.rt_ms !== null)
    .map((t) => t.rt_ms as number)
  const out: Record<string, number> = {
    commission_errors: holds.filter((t) => t.correct === false).length,
    accuracy: scored.length ? scored.filter((t) => t.correct === true).length / scored.length : 0,
  }
  const med = median(goRts)
  if (med !== null) out['go_rt_ms'] = med
  return out
}

export const game: GameModule = {
  id: 'hold_it',
  name: 'Hold It',
  instructions: "Press for every circle. When the hexagon marked Hold appears, don't press.",
  keysHint: 'Space, or tap Go.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['go_ratio'] ?? 0.75,
      spec.knobs['isi_ms'] ?? 900,
    )
    return itemsToTimeline(HoldPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
