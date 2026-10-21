import type { ExerciseSpec } from '../api/types'
import { mulberry32 } from '../lib/rng'
import type { TrialRecord } from '../taskhost/types'
import { dPrime, makeItems as echoItems, metrics as echoMetrics } from './echo/plugin'
import { GAMES } from './index'
import { keyForInk, makeItems as inkItems, metrics as inkMetrics } from './ink_clash/plugin'
import { keyFor, makeItems as quickItems, metrics as quickMetrics } from './quick_draw/plugin'

const rec = (over: Partial<TrialRecord>): TrialRecord => ({
  trial_index: 0,
  practice: false,
  stimulus: {},
  response: null,
  correct: true,
  rt_ms: 500,
  ...over,
})

const spec = (game_id: string, knobs: Record<string, number>, practice = 0): ExerciseSpec => ({
  round_id: 'r',
  game_id,
  mode: 'train',
  target_p: 0.8,
  level: 0.4,
  difficulty_b: 0,
  knobs,
  seed: 7,
  practice_trials: practice,
  duration_s: 60,
  reason: 'test',
  content: null,
  content_item_id: null,
  theme: null,
})

test('Quick Draw items follow the knobs and keys', () => {
  const items = quickItems(mulberry32(1), 4, 600, 20)
  expect(items.every((i) => i.position >= 0 && i.position < 4 && i.deadline_ms === 600)).toBe(true)
  expect(keyFor({ position: 2, choices: 4 })).toBe('j')
  expect(keyFor({ position: 0, choices: 1 })).toBe(' ')
})

test('Quick Draw metrics match a hand-calculated fixture', () => {
  const trials = [
    rec({ rt_ms: 300 }),
    rec({ rt_ms: 500 }),
    rec({ rt_ms: 400 }),
    rec({ correct: false, rt_ms: 200 }),
    rec({ practice: true, rt_ms: 100 }),
  ]
  expect(quickMetrics(trials)).toEqual({ accuracy: 0.75, median_rt_ms: 400 })
})

test('Ink Clash mismatch share follows the knob', () => {
  const items = inkItems(mulberry32(3), 400, 0.75, 1500, false)
  const mismatched = items.filter((i) => !i.congruent).length / items.length
  expect(mismatched).toBeGreaterThan(0.65)
  expect(mismatched).toBeLessThan(0.85)
  for (const i of items) expect(i.congruent).toBe(i.word === i.ink)
  const first = items[0]
  if (!first) throw new Error('no items')
  expect(['d', 'f', 'j', 'k']).toContain(keyForInk(first))
})

test('Ink Clash Stroop effect matches a hand-calculated fixture', () => {
  const trials = [
    rec({ stimulus: { congruent: true }, rt_ms: 600 }),
    rec({ stimulus: { congruent: true }, rt_ms: 700 }),
    rec({ stimulus: { congruent: false }, rt_ms: 800 }),
    rec({ stimulus: { congruent: false }, rt_ms: 900 }),
    rec({ stimulus: { congruent: false }, correct: false, rt_ms: 300 }),
  ]
  expect(inkMetrics(trials)).toEqual({ accuracy: 0.8, stroop_effect_ms: 200 })
})

test('Echo targets are real n-back matches and warm-up letters are never targets', () => {
  const items = echoItems(mulberry32(5), 2, 2000, 200)
  items.forEach((item, i) => {
    if (i < 2) {
      expect(item.warmup).toBe(true)
      expect(item.is_target).toBe(false)
    } else {
      expect(item.is_target).toBe(item.letter === items[i - 2]?.letter)
    }
  })
  const rate = items.filter((i) => i.is_target).length / (items.length - 2)
  expect(rate).toBeGreaterThan(0.2)
  expect(rate).toBeLessThan(0.4)
})

test('Echo metrics and d-prime', () => {
  expect(dPrime(5, 5, 5, 5)).toBeCloseTo(0, 6)
  expect(dPrime(9, 1, 1, 9)).toBeGreaterThan(1.5)
  const trials = [
    rec({ stimulus: { is_target: true }, correct: true }),
    rec({ stimulus: { is_target: true }, correct: false }),
    rec({ stimulus: { is_target: false }, correct: true }),
    rec({ stimulus: { is_target: false }, correct: false }),
  ]
  expect(echoMetrics(trials)).toMatchObject({ hits: 1, false_alarms: 1, accuracy: 0.5 })
})

const SELF_CONTAINED = [
  'quick_draw',
  'ink_clash',
  'echo',
  'arrow_storm',
  'odd_one_out',
  'hold_it',
  'symbol_code',
  'switch',
  'turn_it',
  'number_line',
]
const NEEDS_CONTENT = ['souk_rush', 'pattern_gap', 'spot_the_mistake']

test('every self-contained game builds a seeded timeline with its practice trials first', () => {
  const knobs = {
    choices: 2,
    deadline_ms: 800,
    incongruent_ratio: 0.5,
    shuffled_buttons: 0,
    n: 1,
    pace_ms: 2000,
    flankers: 2,
    set_size: 8,
    similarity: 0.2,
    go_ratio: 0.75,
    isi_ms: 900,
    key_size: 6,
    switch_rate: 0.3,
    cue_time_ms: 500,
    max_angle: 90,
    range_max: 100,
  }
  for (const id of SELF_CONTAINED) {
    const game = GAMES[id]
    if (!game) throw new Error(id)
    const a = game.timeline({ spec: spec(id, knobs, 3), rng: mulberry32(9), e2e: false })
    const b = game.timeline({ spec: spec(id, knobs, 3), rng: mulberry32(9), e2e: false })
    expect(a.map((t) => t['item'])).toEqual(b.map((t) => t['item']))
    expect(a.slice(0, 3).every((t) => t['practice'] === true)).toBe(true)
    expect(a.slice(3).some((t) => t['practice'] === false)).toBe(true)
  }
})

test('content games refuse to start without server content', () => {
  for (const id of NEEDS_CONTENT) {
    const game = GAMES[id]
    if (!game) throw new Error(id)
    expect(() => game.timeline({ spec: spec(id, {}, 0), rng: mulberry32(1), e2e: false })).toThrow(
      /server/,
    )
  }
  expect(Object.keys(GAMES)).toHaveLength(35)
})
