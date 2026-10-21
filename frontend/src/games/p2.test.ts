import type { ExerciseSpec } from '../api/types'
import { mulberry32 } from '../lib/rng'
import { calibration } from '../taskhost/calibration'
import { isProbed } from '../taskhost/plugin'
import type { TrialRecord } from '../taskhost/types'
import { metrics as brakeMetrics } from './brake/plugin'
import { backwards, digitsOnly } from './digits_back/plugin'
import { describe as route, parseInstructions, path, run } from './guide_the_robot/plugin'
import { GAMES } from './index'
import { ANSWERS, makeItems as lockItems } from './logic_lock/plugin'
import { makeItems as mathsItems } from './quick_maths/plugin'
import { REFERENCES } from './secret_rules/plugin'
import { makeItems as teachItems, rubric } from './teach_me/plugin'
import { apply, makeItems as towerItems } from './tower/plugin'
import { validWords } from './word_burst/plugin'
import { alternating } from './shared/trail'

const rec = (over: Partial<TrialRecord>): TrialRecord => ({
  trial_index: 0,
  practice: false,
  stimulus: {},
  response: null,
  correct: true,
  rt_ms: 500,
  ...over,
})

const spec = (game_id: string, content: Record<string, unknown> | null = null): ExerciseSpec => ({
  round_id: 'r',
  game_id,
  mode: 'train',
  target_p: 0.8,
  level: 0.4,
  difficulty_b: 0,
  knobs: {},
  seed: 7,
  practice_trials: 1,
  duration_s: 60,
  reason: 'test',
  content,
  content_item_id: null,
  theme: null,
})

const P2 = [
  'brake',
  'look_here',
  'night_guard',
  'control_tower',
  'digits_back',
  'seen_it',
  'twins',
  'connect',
  'zigzag',
  'secret_rules',
  'tower',
  'guide_the_robot',
  'logic_lock',
  'word_burst',
  'scramble',
  'teach_me',
  'which_jar',
  'quick_maths',
  'balloon_pump',
]

test('every P2 game builds the same timeline from the same seed, with default knobs', () => {
  for (const id of P2) {
    const game = GAMES[id]
    if (!game) throw new Error(id)
    const a = game.timeline({ spec: spec(id), rng: mulberry32(3), e2e: false })
    const b = game.timeline({ spec: spec(id), rng: mulberry32(3), e2e: false })
    expect(a.length, id).toBeGreaterThan(0)
    expect(a.map((t) => t['item'])).toEqual(b.map((t) => t['item']))
  }
})

test('Callback plays the words the server sends and refuses without them', () => {
  const game = GAMES['callback']
  if (!game) throw new Error('callback')
  expect(() => game.timeline({ spec: spec('callback'), rng: mulberry32(1), e2e: false })).toThrow()
  const t = game.timeline({
    spec: spec('callback', { words: ['salt', 'mint'] }),
    rng: mulberry32(1),
    e2e: false,
  })
  expect(t[0]?.['item']).toEqual({ words: ['salt', 'mint'] })
})

test('Logic Lock answers follow the logic of each form', () => {
  const expected = { forward: 0, backward: 1, affirm_consequent: 2, deny_antecedent: 2 }
  const items = lockItems(mulberry32(2), 200, 3)
  for (const i of items) {
    expect(i.answer).toBe(expected[i.form])
    expect(i.premises).toHaveLength(3)
  }
  expect(new Set(items.map((i) => i.form)).size).toBe(4)
  expect(ANSWERS[2]).toBe('Can’t tell')
})

test('Quick Maths answers are whole numbers and follow the operations knob', () => {
  const items = mathsItems(mulberry32(4), 300, 4, 50)
  for (const i of items) expect(Number.isInteger(i.answer) && i.answer >= 0).toBe(true)
  expect(new Set(items.map((i) => i.op)).size).toBe(4)
  expect(new Set(mathsItems(mulberry32(4), 50, 1, 50).map((i) => i.op))).toEqual(new Set(['+']))
})

test('Tower problems are solvable in exactly their minimum moves', () => {
  for (const p of towerItems(mulberry32(5), 30, 4)) {
    expect(p.solution).toHaveLength(p.min_moves)
    const end = p.solution.reduce(apply, p.start)
    expect(end).toEqual(p.goal)
  }
})

test('Guide the Robot: the written solution reaches the star, vague instructions fail', () => {
  const item = { size: 3, walls: [[1, 0]] as [number, number][], start: [0, 0] as [number, number] }
  const steps = path(3, item.walls, [0, 0], [2, 0])
  expect(steps).toHaveLength(4) // around the wall
  const text = route(steps ?? [])
  expect(text).toBe('down 1, right 2, up 1')
  const parsed = parseInstructions(text)
  expect(parsed.vague).toBe(false)
  const robot = {
    ...item,
    stars: [[2, 0]] as [number, number][],
    intended: 0,
    ambiguous: false,
    shortest: 4,
    solution: text,
  }
  expect(run(robot, parsed.steps)).toEqual({ at: [2, 0], bumped: false })
  expect(run(robot, parseInstructions('right 1').steps).bumped).toBe(true)
  expect(parseInstructions('go to the star').vague).toBe(true)
  expect(parseInstructions('up, then right 2').vague).toBe(true)
})

test('Teach Me: the rubric counts key ideas; each round has one ambiguous request', () => {
  const items = teachItems(mulberry32(6), 3, 0.4)
  expect(items.filter((i) => i.other !== null)).toHaveLength(1)
  const topic = items[0]?.topic
  if (!topic) throw new Error('no topic')
  const full = rubric(topic.ideas.map((i) => i.idea).join(' '), topic)
  expect(full.score).toBeGreaterThanOrEqual(0.5)
  expect(rubric('I am not sure at all, sorry', topic).score).toBe(0)
})

test('Word Burst counts each real-looking word once', () => {
  expect(validWords('sun sun suns sky sssss so salt, pear', 's')).toEqual(['sun', 'sky', 'salt'])
})

test('Digits Back and the trail order', () => {
  expect(backwards([3, 8, 2])).toBe('283')
  expect(digitsOnly('2 8-3')).toBe('283')
  expect(alternating(5)).toEqual(['1', 'A', '2', 'B', '3'])
  expect(REFERENCES[2]).toEqual({ colour: 2, shape: 2, count: 2, frame: 2 })
})

test('Brake stop-signal reaction time, median method', () => {
  const trials = [
    rec({ stimulus: { stop: false }, rt_ms: 400 }),
    rec({ stimulus: { stop: false }, rt_ms: 500 }),
    rec({ stimulus: { stop: false }, rt_ms: 600 }),
    rec({ stimulus: { stop: true, stop_delay_ms: 200 }, correct: true, rt_ms: null }),
    rec({ stimulus: { stop: true, stop_delay_ms: 300 }, correct: false, rt_ms: 450 }),
  ]
  expect(brakeMetrics(trials)).toEqual({ go_accuracy: 1, stop_success: 0.5, ssrt_ms: 250 })
})

test('How sure are you: about one answer in ten is probed, never practice, and calibration', () => {
  const probed = Array.from({ length: 100 }, (_, i) => isProbed(i, 3)).filter(Boolean)
  expect(probed).toHaveLength(10)
  expect([0, 1, 2].some((i) => isProbed(i, 3))).toBe(false)
  const m = calibration([
    rec({ confidence: 1, correct: true }),
    rec({ confidence: 0.5, correct: false }),
    rec({ correct: true }),
  ])
  expect(m).toEqual({ probes: 2, calibration_error: 0.25, brier_score: 0.125 })
  expect(calibration([rec({})])).toEqual({})
})
