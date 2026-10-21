import { mulberry32 } from '../lib/rng'
import type { TrialRecord } from '../taskhost/types'
import { makeItems as arrowItems, metrics as arrowMetrics } from './arrow_storm/plugin'
import { metrics as holdMetrics } from './hold_it/plugin'
import { expected, makeItems as pathItems } from './light_path/plugin'
import { recalled } from './market_list/plugin'
import { makeItems as lineItems, metrics as lineMetrics, scoreFor } from './number_line/plugin'
import { metrics as searchMetrics } from './odd_one_out/plugin'
import { metrics as gapMetrics } from './pattern_gap/plugin'
import { finalOrders, type Scene } from './souk_rush/plugin'
import { metrics as mistakeMetrics } from './spot_the_mistake/plugin'
import { expectedKey, makeItems as switchItems, metrics as switchMetrics } from './switch/plugin'
import { metrics as codeMetrics } from './symbol_code/plugin'
import { metrics as turnMetrics } from './turn_it/plugin'

const rec = (over: Partial<TrialRecord>): TrialRecord => ({
  trial_index: 0,
  practice: false,
  stimulus: {},
  response: null,
  correct: true,
  rt_ms: 500,
  ...over,
})

test('Arrow Storm flanker cost (hand fixture) and item mix', () => {
  const trials = [
    rec({ stimulus: { congruent: true }, rt_ms: 400 }),
    rec({ stimulus: { congruent: true }, rt_ms: 420 }),
    rec({ stimulus: { congruent: false }, rt_ms: 470 }),
    rec({ stimulus: { congruent: false }, rt_ms: 490 }),
  ]
  expect(arrowMetrics(trials)).toEqual({ accuracy: 1, flanker_cost_ms: 70 })
  const items = arrowItems(mulberry32(1), 400, 0.7, 4, 900)
  const share = items.filter((i) => !i.congruent).length / items.length
  expect(share).toBeGreaterThan(0.6)
  expect(share).toBeLessThan(0.8)
})

test('Odd One Out search slope (hand fixture)', () => {
  const trials = [
    rec({ stimulus: { set_size: 8 }, rt_ms: 600 }),
    rec({ stimulus: { set_size: 8 }, rt_ms: 640 }),
    rec({ stimulus: { set_size: 16 }, rt_ms: 840 }),
    rec({ stimulus: { set_size: 16 }, rt_ms: 880 }),
  ]
  expect(searchMetrics(trials)).toEqual({ accuracy: 1, search_slope_ms_per_item: 30 })
})

test('Hold It commission errors (hand fixture)', () => {
  const trials = [
    rec({ stimulus: { go: true }, rt_ms: 350 }),
    rec({ stimulus: { go: true }, rt_ms: 450 }),
    rec({ stimulus: { go: false }, correct: false, rt_ms: 300 }),
    rec({ stimulus: { go: false }, rt_ms: null }),
  ]
  expect(holdMetrics(trials)).toEqual({ commission_errors: 1, accuracy: 0.75, go_rt_ms: 400 })
})

test('Light Path sequences never repeat a square twice in a row; backwards reverses', () => {
  for (const item of pathItems(mulberry32(2), 50, 6, 800, true)) {
    expect(item.sequence).toHaveLength(6)
    item.sequence.forEach((v, i) => {
      if (i > 0) expect(v).not.toBe(item.sequence[i - 1])
    })
    expect(expected(item)).toEqual([...item.sequence].reverse())
  }
})

test('Market List recall is case- and order-insensitive', () => {
  expect(recalled('Goal, ball  REFEREE x', ['goal', 'ball', 'referee', 'net'])).toEqual(
    new Set(['goal', 'ball', 'referee']),
  )
})

test('Souk Rush applies changes to the final orders', () => {
  const scene: Scene = {
    orders: [{ customer: 'Amira', items: ['figs', 'dates'], line: '' }],
    changes: [{ customer: 'Amira', remove: 'figs', add: 'lemons', line: '' }],
  }
  expect(finalOrders(scene).get('Amira')).toEqual(['lemons', 'dates'])
})

test('Symbol Code items per minute (hand fixture)', () => {
  const trials = [rec({ rt_ms: 1000 }), rec({ rt_ms: 1000 }), rec({ correct: false, rt_ms: 1000 })]
  expect(codeMetrics(trials)).toEqual({ accuracy: 2 / 3, items_per_min: 40 })
})

test('Switch cost (hand fixture) and expected keys', () => {
  const trials = [
    rec({ stimulus: { switched: false }, rt_ms: 500 }),
    rec({ stimulus: { switched: false }, rt_ms: 520 }),
    rec({ stimulus: { switched: true }, rt_ms: 640 }),
    rec({ stimulus: { switched: true }, rt_ms: 660 }),
  ]
  expect(switchMetrics(trials)).toEqual({ accuracy: 1, switch_cost_ms: 140 })
  const items = switchItems(mulberry32(3), 200, 0.5, 300)
  const switches = items.filter((i) => i.switched).length / items.length
  expect(switches).toBeGreaterThan(0.4)
  for (const i of items)
    expect(expectedKey(i)).toBe((i.rule === 'colour' ? i.colour : i.shape) === 0 ? 'f' : 'j')
})

test('Pattern Gap counts hints used', () => {
  expect(gapMetrics([rec({ hint_level: 2 }), rec({ hint_level: 0, correct: false })])).toEqual({
    accuracy: 0.5,
    hints_used: 2,
  })
})

test("Spot the AI's Mistake uses balanced accuracy", () => {
  const trials = [
    rec({ stimulus: { has_error: true } }),
    rec({ stimulus: { has_error: true }, correct: false }),
    rec({ stimulus: { has_error: false } }),
    rec({ stimulus: { has_error: false } }),
  ]
  // Accepting everything as right would score 0.5 on wrong ones... here 0.5 and 1.0: mean 0.75.
  expect(mistakeMetrics(trials).balanced_accuracy).toBe(0.75)
})

test('Turn It angle slope (hand fixture)', () => {
  const trials = [
    rec({ stimulus: { angle: 0 }, rt_ms: 800 }),
    rec({ stimulus: { angle: 90 }, rt_ms: 1250 }),
    rec({ stimulus: { angle: 180 }, rt_ms: 1700 }),
  ]
  expect(turnMetrics(trials).angle_rt_slope).toBeCloseTo(5, 6)
})

test('Number Line scores closeness continuously', () => {
  const item = { target: 30, max: 100 }
  expect(scoreFor(30, item)).toBe(1)
  expect(scoreFor(40, item)).toBeCloseTo(0.9)
  expect(lineItems(mulberry32(4), 10, 120).every((i) => i.max === 200)).toBe(true)
  const trials = [
    rec({ stimulus: { target: 30, max: 100 }, response: { placed: 40 }, correct: false }),
    rec({ stimulus: { target: 50, max: 100 }, response: { placed: 52 } }),
  ]
  expect(lineMetrics(trials).mean_abs_error_share).toBeCloseTo(0.06)
})
