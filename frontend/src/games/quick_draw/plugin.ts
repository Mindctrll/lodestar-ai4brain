import { parse } from 'yaml'

import { median, randInt, type Rng } from '../../lib/rng'
import { itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

interface Config {
  trials: number
  keys: string[]
  single_key: string
  foreperiod_ms: [number, number]
}
const config = parse(rawConfig) as Config

export interface QuickDrawItem {
  position: number
  choices: number
  foreperiod_ms: number
  deadline_ms: number
}

export function keyFor(item: Pick<QuickDrawItem, 'position' | 'choices'>): string {
  return item.choices === 1 ? config.single_key : (config.keys[item.position] ?? 'd')
}

export function makeItems(
  rng: Rng,
  choices: number,
  deadlineMs: number,
  count: number,
): QuickDrawItem[] {
  return Array.from({ length: count }, () => ({
    position: randInt(rng, 0, choices - 1),
    choices,
    foreperiod_ms: randInt(rng, config.foreperiod_ms[0], config.foreperiod_ms[1]),
    deadline_ms: deadlineMs,
  }))
}

const QuickDrawPlugin = makePlugin<QuickDrawItem>(
  'najma-quick-draw',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const boxes = Array.from({ length: item.choices }, (_, i) => {
      const box = document.createElement('button')
      box.type = 'button'
      box.className = 'qd-box'
      box.dataset['testid'] = `box-${String(i)}`
      box.setAttribute(
        'aria-label',
        `Box ${String(i + 1)}, key ${keyFor({ position: i, choices: item.choices }).trim() || 'Space'}`,
      )
      const label = document.createElement('span')
      label.className = 'qd-key'
      label.textContent =
        keyFor({ position: i, choices: item.choices }).trim().toUpperCase() || 'SPACE'
      box.appendChild(label)
      return box
    })
    const row = document.createElement('div')
    row.className = 'qd-row'
    row.append(...boxes)
    stage.append(row)
    await new Promise((resolve) => setTimeout(resolve, item.foreperiod_ms))
    const target = boxes[item.position]
    if (!target) throw new Error('bad position')
    const star = document.createElement('span')
    star.className = 'qd-star'
    star.textContent = '★'
    target.appendChild(star)
    const expected = keyFor(item)
    const response = await waitForResponse(jsPsych, {
      keys: item.choices === 1 ? [config.single_key] : config.keys.slice(0, item.choices),
      targets: boxes.map((element, i) => ({
        element,
        key: keyFor({ position: i, choices: item.choices }),
      })),
      deadlineMs: item.deadline_ms,
      onReady: () => {
        if (e2e) stage.dataset['answer'] = keyFor(item)
      },
    })
    const correct = response.key === expected
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
  const rts = scored
    .filter((t) => t.correct === true && t.rt_ms !== null)
    .map((t) => t.rt_ms as number)
  const out: Record<string, number> = {
    accuracy: scored.length ? scored.filter((t) => t.correct === true).length / scored.length : 0,
  }
  const med = median(rts)
  if (med !== null) out['median_rt_ms'] = med
  return out
}

export const game: GameModule = {
  id: 'quick_draw',
  name: 'Quick Draw',
  instructions:
    'A star will appear in one of the boxes after a short wait. Press its key, or tap the box, as fast as you can.',
  keysHint: 'Space for one box; D F J K for four boxes.',
  timeline({ spec, rng, e2e }) {
    const choices = Math.max(1, Math.min(4, Math.round(spec.knobs['choices'] ?? 1)))
    const deadline = spec.knobs['deadline_ms'] ?? 1200
    const items = makeItems(rng, choices, deadline, spec.practice_trials + config.trials)
    return itemsToTimeline(QuickDrawPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
