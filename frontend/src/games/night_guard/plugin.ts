import { parse } from 'yaml'

import { median, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { dPrime } from '../echo/plugin'
import { choose, scored } from '../shared/ask'
import { node, svg } from '../shared/svg'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { items: number; pace_ms: number; show_ms: number }

export interface WatchItem {
  signal: boolean
  /** Size of the gap in a signal ring, in degrees: smaller is harder to spot. */
  gap_deg: number
  pace_ms: number
}

export function makeItems(rng: Rng, count: number, signalRate: number, subtlety: number) {
  const gap = Math.round(90 - 75 * subtlety)
  return Array.from({ length: count }, (_, i): WatchItem => ({
    signal: i > 0 && rng() < signalRate,
    gap_deg: gap,
    pace_ms: config.pace_ms,
  }))
}

function ring(gapDeg: number | null): SVGSVGElement {
  const s = svg(100, 100, 'A light on the watch')
  const r = 36
  const c = 2 * Math.PI * r
  const gap = gapDeg === null ? 0 : (gapDeg / 360) * c
  s.append(
    node('circle', {
      cx: 50,
      cy: 50,
      r,
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': 8,
      'stroke-dasharray': `${String(c - gap)} ${String(gap)}`,
      transform: 'rotate(-90 50 50)',
    }),
  )
  return s
}

const WatchPlugin = makePlugin<WatchItem>(
  'najma-night-guard',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const light = el('div', 'ng-light')
    light.append(ring(item.signal ? item.gap_deg : null))
    stage.append(light)
    const started = performance.now()
    const hide = window.setTimeout(() => {
      light.style.visibility = 'hidden'
    }, config.show_ms)
    const { index, rt } = await choose(
      jsPsych,
      stage,
      e2e,
      ['Signal (Space)'],
      item.signal ? 0 : null,
      {
        keys: [' '],
        deadlineMs: item.pace_ms,
      },
    )
    window.clearTimeout(hide)
    const correct = (index !== null) === item.signal
    if (practice) await practiceFeedback(stage, correct)
    await wait(Math.max(0, item.pace_ms - (performance.now() - started)))
    return {
      stimulus: { ...item },
      response: index === null ? null : { pressed: true },
      correct,
      rt_ms: rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const signals = s.filter((t) => t.stimulus['signal'] === true)
  const quiet = s.filter((t) => t.stimulus['signal'] !== true)
  const hits = signals.filter((t) => t.correct === true)
  const falseAlarms = quiet.filter((t) => t.correct === false).length
  const out: Record<string, number> = {
    hits: hits.length,
    false_alarms: falseAlarms,
    d_prime: dPrime(
      hits.length,
      signals.length - hits.length,
      falseAlarms,
      quiet.length - falseAlarms,
    ),
  }
  // Vigilance decrement: are answers to signals slower in the last third than in the first?
  const third = Math.floor(s.length / 3)
  const rts = (from: number, to: number) =>
    median(
      hits
        .filter((t) => s.indexOf(t) >= from && s.indexOf(t) < to && t.rt_ms !== null)
        .map((t) => t.rt_ms as number),
    )
  const early = rts(0, third)
  const late = rts(s.length - third, s.length)
  if (third > 0 && early !== null && late !== null) out['rt_drift_ms'] = late - early
  return out
}

export const game: GameModule = {
  id: 'night_guard',
  name: 'Night Guard',
  instructions:
    'Watch the light. Most of the time it’s a full ring. Press Signal only when the ring has a gap. Signals are rare, so stay with it.',
  keysHint: 'Space, or tap Signal.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.items,
      spec.knobs['signal_rate'] ?? 0.1,
      spec.knobs['subtlety'] ?? 0.5,
    )
    return itemsToTimeline(WatchPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
