import { parse } from 'yaml'

import { median, randInt, type Rng } from '../../lib/rng'
import {
  el,
  itemsToTimeline,
  makePlugin,
  markAnswer,
  type TrialOutcome,
} from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

interface Config {
  trials: number
  keys: string[]
  single_key: string
  foreperiod_ms: [number, number]
  tap_in_time: { beats: number; period_ms: number }
}
const config = parse(rawConfig) as Config

export interface QuickDrawItem {
  position: number
  choices: number
  foreperiod_ms: number
  deadline_ms: number
}

/** Device-lag calibration (docs/plan/06): at onboarding and check-ups the round starts with
 * "tap in time". Each tap's offset from its flash is the screen and input delay plus a little
 * human timing noise; the server takes the median (backend/scoring/quality.py: device_lag). */
export interface TapInTimeItem {
  kind: 'tap_in_time'
  beats: number
  period_ms: number
}

/** For each flash, the offset of the nearest tap within half a beat, or null if none. */
export function tapOffsets(flashes: number[], taps: number[], periodMs: number): (number | null)[] {
  return flashes.map((flash) => {
    let best: number | null = null
    for (const tap of taps) {
      const offset = tap - flash
      if (Math.abs(offset) <= periodMs / 2 && (best === null || Math.abs(offset) < Math.abs(best)))
        best = offset
    }
    return best
  })
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)))
const painted = () =>
  new Promise<number>((resolve) => {
    requestAnimationFrame(() => {
      resolve(performance.now())
    })
  })

async function tapInTime(stage: HTMLElement, item: TapInTimeItem): Promise<TrialOutcome[]> {
  const box = el('button', 'qd-box')
  box.type = 'button'
  box.dataset['testid'] = 'tap-in-time'
  box.setAttribute('aria-label', 'Tap in time with the star')
  const hint = 'First, tap in time: press Space or tap the box each time the star lights up.'
  stage.append(el('p', '', hint), box)
  const taps: number[] = []
  const onKey = (event: KeyboardEvent) => {
    if (event.key !== ' ' || event.repeat) return
    event.preventDefault()
    taps.push(performance.now())
  }
  const onTap = (event: PointerEvent) => {
    event.preventDefault()
    taps.push(performance.now())
  }
  document.addEventListener('keydown', onKey)
  box.addEventListener('pointerdown', onTap)
  const star = el('span', 'qd-star', '★')
  const flashes: number[] = []
  const t0 = performance.now() + 1000
  for (let beat = 0; beat < item.beats; beat++) {
    await wait(t0 + beat * item.period_ms - performance.now())
    box.appendChild(star)
    flashes.push(await painted()) // timed like a response: from the frame that shows it
    await wait(150)
    star.remove()
  }
  await wait(item.period_ms / 2)
  document.removeEventListener('keydown', onKey)
  box.removeEventListener('pointerdown', onTap)
  return tapOffsets(flashes, taps, item.period_ms).map((offset, beat) => ({
    stimulus: { kind: item.kind, beat, period_ms: item.period_ms },
    response: offset === null ? null : { offset_ms: offset },
    correct: null,
    rt_ms: null,
  }))
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

const QuickDrawPlugin = makePlugin<QuickDrawItem | TapInTimeItem>(
  'najma-quick-draw',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    if ('kind' in item) return tapInTime(stage, item)
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
        markAnswer(stage, e2e, `key:${expected === ' ' ? 'Space' : expected}`)
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
    // Calibrate the device lag when measuring (onboarding, check-ups); not in end-to-end tests.
    if (spec.mode !== 'assess' || e2e)
      return itemsToTimeline(QuickDrawPlugin, items, spec.practice_trials, e2e)
    const calibrate: TapInTimeItem = { kind: 'tap_in_time', ...config.tap_in_time }
    return itemsToTimeline(QuickDrawPlugin, [calibrate, ...items], spec.practice_trials + 1, e2e)
  },
  metrics,
}
