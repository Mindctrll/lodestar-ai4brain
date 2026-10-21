import { mulberry32 } from '../../lib/rng'
import type { TrialRecord } from '../../taskhost/types'
import { GAMES } from '../index'
import { makeItems, metrics, onsets } from './plugin'

const rec = (shift_ms: number, off: boolean | null, correct: boolean): TrialRecord => ({
  trial_index: 0,
  practice: false,
  stimulus: { shift_ms },
  response: off === null ? null : { off },
  correct,
  rt_ms: 600,
})

test('Off Beat: half the steps are off, by the knob’s share of the beat', () => {
  const items = makeItems(mulberry32(4), 16, 5, 10)
  const off = items.filter((i) => i.shift_ms !== 0)
  expect(off).toHaveLength(8)
  expect(off.every((i) => Math.abs(i.shift_ms) === 60 && i.beats === 5)).toBe(true)
  expect(makeItems(mulberry32(4), 16, 5, 10)).toEqual(items)
})

test('Off Beat: only the last beat moves', () => {
  const item = { beats: 4, beat_ms: 600, shift_ms: -90, deadline_ms: 4000 }
  expect(onsets(item)).toEqual([0, 600, 1200, 1710])
})

test('Off Beat metrics match a hand-calculated fixture', () => {
  const trials = [
    rec(60, true, true),
    rec(-60, false, false),
    rec(0, false, true),
    rec(0, true, false),
    rec(0, null, false),
    { ...rec(60, true, true), practice: true },
  ]
  expect(metrics(trials)).toEqual({ accuracy: 0.4, hit_rate: 0.5, false_alarm_rate: 1 / 3 })
})

test('Off Beat is registered and builds its practice steps first', () => {
  const game = GAMES['off_beat']
  if (!game) throw new Error('off_beat missing')
  const spec = {
    round_id: 'r',
    game_id: 'off_beat',
    mode: 'train' as const,
    target_p: 0.8,
    level: 0.5,
    difficulty_b: 0,
    knobs: { shift_pct: 18, beats: 5 },
    seed: 7,
    practice_trials: 3,
    duration_s: 90,
    reason: 'test',
    content: null,
    content_item_id: null,
    theme: null,
  }
  const timeline = game.timeline({ spec, rng: mulberry32(7), e2e: false })
  expect(timeline).toHaveLength(19)
  expect(timeline.filter((t) => t['practice'] === true)).toHaveLength(3)
})
