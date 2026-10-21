import { parse } from 'yaml'

import { median, pick, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { choose, scored } from '../shared/ask'
import rawConfig from './config.yaml?raw'

interface Config {
  trials: number
  stop_delay_start_ms: number
  stop_delay_step_ms: number
  stop_delay_min_ms: number
}
const config = parse(rawConfig) as Config

export interface BrakeItem {
  direction: 'left' | 'right'
  stop: boolean
  deadline_ms: number
}

export function makeItems(rng: Rng, count: number, stopRatio: number, deadline: number) {
  return Array.from({ length: count }, (_, i): BrakeItem => ({
    direction: pick(rng, ['left', 'right'] as const),
    stop: i > 0 && rng() < stopRatio,
    deadline_ms: deadline,
  }))
}

/** The stop delay staircase (docs/plan/07): longer after a successful stop, shorter after a
 * failed one, so stopping succeeds about half the time. Reset at the start of each round. */
const staircase = { delay: config.stop_delay_start_ms }

function beep(): void {
  try {
    const audio = new AudioContext()
    const tone = audio.createOscillator()
    tone.frequency.value = 880
    tone.connect(audio.destination)
    tone.start()
    tone.stop(audio.currentTime + 0.15)
  } catch {
    // No sound available: the red ring alone is the stop signal.
  }
}

const BrakePlugin = makePlugin<BrakeItem>(
  'najma-brake',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const arrow = el('div', 'brake-arrow', item.direction === 'left' ? '←' : '→')
    arrow.dataset['testid'] = 'brake-arrow'
    stage.append(arrow)
    const delay = staircase.delay
    let timer = 0
    const { index, rt } = await choose(
      jsPsych,
      stage,
      e2e,
      ['Left', 'Right'],
      item.stop ? null : item.direction === 'left' ? 0 : 1,
      {
        keys: ['arrowleft', 'arrowright'],
        deadlineMs: item.deadline_ms,
        onReady: () => {
          if (item.stop)
            timer = window.setTimeout(() => {
              arrow.classList.add('is-stop')
              beep()
            }, delay)
        },
      },
    )
    window.clearTimeout(timer)
    const pressed = index !== null
    const correct = item.stop ? !pressed : index === (item.direction === 'left' ? 0 : 1)
    if (item.stop) {
      const step = config.stop_delay_step_ms
      staircase.delay = Math.max(config.stop_delay_min_ms, delay + (pressed ? -step : step))
    }
    if (practice) await practiceFeedback(stage, correct)
    else await wait(300)
    return {
      stimulus: { ...item, stop_delay_ms: item.stop ? delay : null },
      response: pressed ? { side: index === 0 ? 'left' : 'right' } : null,
      correct,
      rt_ms: rt,
    }
  },
)

/** Stop-signal reaction time, median method (Logan, 1994): median go time minus mean stop delay. */
export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const go = s.filter((t) => t.stimulus['stop'] !== true)
  const stops = s.filter((t) => t.stimulus['stop'] === true)
  const out: Record<string, number> = {
    go_accuracy: go.length ? go.filter((t) => t.correct === true).length / go.length : 0,
    stop_success: stops.length ? stops.filter((t) => t.correct === true).length / stops.length : 0,
  }
  const goRt = median(go.filter((t) => t.correct === true).map((t) => t.rt_ms ?? 0))
  if (goRt !== null && stops.length) {
    const delays = stops.map((t) => Number(t.stimulus['stop_delay_ms']))
    out['ssrt_ms'] = goRt - delays.reduce((a, b) => a + b, 0) / delays.length
  }
  return out
}

export const game: GameModule = {
  id: 'brake',
  name: 'Brake',
  instructions:
    'Press the arrow that matches the one on screen, fast. If the arrow turns red (with a beep), don’t press anything.',
  keysHint: 'Left and Right arrow keys, or tap the buttons.',
  timeline({ spec, rng, e2e }) {
    staircase.delay = config.stop_delay_start_ms
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['stop_ratio'] ?? 0.25,
      spec.knobs['go_deadline_ms'] ?? 1000,
    )
    return itemsToTimeline(BrakePlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
