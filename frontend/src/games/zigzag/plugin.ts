import { parse } from 'yaml'

import type { Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { scored } from '../shared/ask'
import {
  alternating,
  makeBoard,
  numbers,
  runTrail,
  trailScore,
  type TrailBoard,
} from '../shared/trail'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { pairs: number; deadline_ms: number }

export interface ZigzagItem {
  part: 'A' | 'B'
  board: TrailBoard
}

/** Each pair is a numbers-only board (part A, the baseline) then an alternating one (part B);
 * B minus A is the cost of switching (Trail Making Test). */
export function makeItems(rng: Rng, pairs: number, circles: number): ZigzagItem[] {
  return Array.from({ length: pairs }, () => [
    { part: 'A' as const, board: makeBoard(rng, numbers(circles)) },
    { part: 'B' as const, board: makeBoard(rng, alternating(circles)) },
  ]).flat()
}

const ZigzagPlugin = makePlugin<ZigzagItem>(
  'lodestar-zigzag',
  async ({ stage, item, practice, e2e }) => {
    stage.append(
      el('p', 'game-prompt', item.part === 'A' ? 'Numbers only: 1, 2, 3…' : 'Switch: 1, A, 2, B…'),
    )
    const result = await runTrail(stage, e2e, item.board, config.deadline_ms)
    if (practice) await practiceFeedback(stage, result.completed)
    // Part A is the baseline; only the switching part scores.
    const score = item.part === 'B' ? trailScore(result, item.board.labels.length) : null
    return {
      stimulus: { part: item.part, count: item.board.labels.length },
      response: { score, time_s: result.time_ms / 1000, errors: result.errors },
      correct: item.part === 'B' ? result.completed && result.errors === 0 : null,
      rt_ms: result.time_ms,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const mean = (part: string) => {
    const times = scored(trials)
      .filter((t) => t.stimulus['part'] === part)
      .map((t) => Number(t.response?.['time_s']))
    return times.length ? times.reduce((a, b) => a + b, 0) / times.length : null
  }
  const a = mean('A')
  const b = mean('B')
  return a !== null && b !== null ? { a_s: a, b_s: b, b_minus_a_s: b - a } : {}
}

export const game: GameModule = {
  id: 'zigzag',
  name: 'Zigzag',
  instructions:
    'First tap the numbers in order. Then switch between numbers and letters: 1, A, 2, B, 3, C and on.',
  keysHint: 'Tap or click each circle in order.',
  timeline({ spec, rng, e2e }) {
    const practice = spec.practice_trials > 0 ? 2 : 0 // one short A and B pair to learn on
    const items = [
      ...(practice ? makeItems(rng, 1, 6) : []),
      ...makeItems(rng, config.pairs, Math.round(spec.knobs['count'] ?? 10)),
    ]
    return itemsToTimeline(ZigzagPlugin, items, practice, e2e)
  },
  metrics,
}
