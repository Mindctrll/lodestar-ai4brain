import { parse } from 'yaml'

import type { Rng } from '../../lib/rng'
import { itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { scored } from '../shared/ask'
import { makeBoard, numbers, runTrail, trailScore, type TrailBoard } from '../shared/trail'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { boards: number; deadline_ms: number; decoys: string }

export function makeItems(rng: Rng, count: number, circles: number, clutter: number): TrailBoard[] {
  const decoys = config.decoys.split('').slice(0, Math.round(clutter * config.decoys.length))
  return Array.from({ length: count }, () => makeBoard(rng, numbers(circles), decoys))
}

const ConnectPlugin = makePlugin<TrailBoard>(
  'lodestar-connect',
  async ({ stage, item, practice, e2e }) => {
    const result = await runTrail(stage, e2e, item, config.deadline_ms)
    const score = trailScore(result, item.labels.length)
    if (practice) await practiceFeedback(stage, result.completed)
    return {
      stimulus: { count: item.labels.length, decoys: item.decoys.length },
      response: { score, time_s: result.time_ms / 1000, errors: result.errors },
      correct: result.completed && result.errors === 0,
      rt_ms: result.time_ms,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const done = scored(trials).filter((t) => t.response?.['score'] !== 0)
  const times = done.map((t) => Number(t.response?.['time_s']))
  return {
    time_s: times.length ? times.reduce((a, b) => a + b, 0) / times.length : 0,
    errors: scored(trials).reduce((n, t) => n + Number(t.response?.['errors'] ?? 0), 0),
  }
}

export const game: GameModule = {
  id: 'connect',
  name: 'Connect',
  instructions: 'Tap the numbers in order, 1, 2, 3 and on, as fast as you can. Ignore the letters.',
  keysHint: 'Tap or click each circle in order.',
  timeline({ spec, rng, e2e }) {
    const practice = Math.min(1, spec.practice_trials)
    const items = makeItems(
      rng,
      practice + config.boards,
      Math.round(spec.knobs['count'] ?? 12),
      spec.knobs['clutter'] ?? 0,
    )
    return itemsToTimeline(ConnectPlugin, items, practice, e2e)
  },
  metrics,
}
