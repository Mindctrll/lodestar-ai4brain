import { parse } from 'yaml'

import { randInt, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { scored, taps } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { balloons: number; max_pumps: number; deadline_ms: number }

export interface BalloonItem {
  /** The pump that pops it (Balloon Analogue Risk Task, Lejuez et al., 2002). */
  pops_at: number
}

export function makeItems(rng: Rng, count: number): BalloonItem[] {
  return Array.from({ length: count }, () => ({ pops_at: randInt(rng, 1, config.max_pumps) }))
}

const BalloonPlugin = makePlugin<BalloonItem>(
  'najma-balloon-pump',
  async ({ stage, item, e2e }) => {
    const balloon = el('div', 'bp-balloon')
    const points = el('p', 'game-prompt', '0 points in this balloon')
    const pump = button('Pump (Space)', 'pump')
    const collect = button('Collect (Enter)', 'collect')
    const row = el('div', 'choice-row')
    row.append(pump, collect)
    stage.append(balloon, points, row)
    let pumps = 0
    const balloonState = { popped: false }
    const started = performance.now()
    await taps(
      [
        { element: pump, key: ' ' },
        { element: collect, key: 'enter' },
      ],
      {
        keys: [' ', 'enter'],
        deadlineMs: config.deadline_ms,
        onReady: () => {
          // End-to-end tests pump a little and collect before it pops.
          const safe = Math.min(3, item.pops_at - 1)
          markAnswer(
            stage,
            e2e,
            `clicks:${[...Array<string>(safe).fill('pump'), 'collect'].join('|')}`,
          )
        },
        onTap: (key) => {
          if (key === 'enter') return true
          pumps += 1
          if (pumps >= item.pops_at) {
            balloonState.popped = true
            return true
          }
          balloon.style.transform = `scale(${String(1 + pumps * 0.04)})`
          points.textContent = `${String(pumps)} points in this balloon`
          return false
        },
      },
    )
    balloon.classList.add(balloonState.popped ? 'is-popped' : 'is-banked')
    points.textContent = balloonState.popped
      ? 'Pop! No points this time.'
      : `${String(pumps)} points collected`
    await wait(700)
    return {
      stimulus: { pops_at: item.pops_at, max_pumps: config.max_pumps },
      response: { pumps, popped: balloonState.popped },
      correct: null, // a style, not right or wrong
      rt_ms: performance.now() - started,
    }
  },
)

/** Adjusted pumps: the mean pumps on balloons that didn't pop. */
export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const kept = s.filter((t) => t.response?.['popped'] !== true)
  const pumps = kept.map((t) => Number(t.response?.['pumps'] ?? 0))
  return {
    adjusted_pumps: pumps.length ? pumps.reduce((a, b) => a + b, 0) / pumps.length : 0,
    popped: s.length - kept.length,
    points: pumps.reduce((a, b) => a + b, 0),
  }
}

export const game: GameModule = {
  id: 'balloon_pump',
  name: 'Balloon Pump',
  instructions:
    'Each pump adds a point, but the balloon may pop and lose them. Collect whenever you like. There’s no right way: this shows your style.',
  keysHint: 'Space to pump, Enter to collect, or tap the buttons.',
  timeline({ spec, rng, e2e }) {
    return itemsToTimeline(
      BalloonPlugin,
      makeItems(rng, config.balloons),
      Math.min(1, spec.practice_trials),
      e2e,
    )
  },
  metrics,
}
