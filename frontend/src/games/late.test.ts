import type { ExerciseSpec } from '../api/types'
import { mulberry32 } from '../lib/rng'
import type { TrialRecord } from '../taskhost/types'
import { deckNet, makeItem as gambleItem, metrics as gambleMetrics } from './card_gamble/plugin'
import { makeItems as foldItems, unfold } from './fold_and_punch/plugin'
import { GAMES } from './index'
import { makeMaze } from './maze_escape/plugin'
import { makeItems as tagItems } from './name_tags/plugin'
import { lettersOnly, makeItems as keepItems } from './sum_and_keep/plugin'
import { metrics as screensMetrics, question } from './two_screens/plugin'
import { makeItems as usesItems, rate } from './unusual_uses/plugin'

const rec = (over: Partial<TrialRecord>): TrialRecord => ({
  trial_index: 0,
  practice: false,
  stimulus: {},
  response: null,
  correct: true,
  rt_ms: 500,
  ...over,
})

const spec = (game_id: string): ExerciseSpec => ({
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
  content: null,
  content_item_id: null,
  theme: null,
  track: null,
})

const LATE = [
  'two_screens',
  'sum_and_keep',
  'name_tags',
  'maze_escape',
  'fold_and_punch',
  'card_gamble',
  'unusual_uses',
]

test('every late game builds the same timeline from the same seed, with default knobs', () => {
  for (const id of LATE) {
    const game = GAMES[id]
    if (!game) throw new Error(id)
    const a = game.timeline({ spec: spec(id), rng: mulberry32(3), e2e: false })
    const b = game.timeline({ spec: spec(id), rng: mulberry32(3), e2e: false })
    expect(a.length, id).toBeGreaterThan(0)
    expect(a.map((t) => t['item'])).toEqual(b.map((t) => t['item']))
  }
})

test('Two Screens questions are right, and the dual-task cost is the slowdown while tracking', () => {
  const rng = mulberry32(1)
  for (let i = 0; i < 100; i++) {
    const q = question(rng)
    const [n, m] = (q.text.match(/\d+/g) ?? []).map(Number)
    const yes = q.text.includes('even') ? (n ?? 0) % 2 === 0 : (n ?? 0) > (m ?? 0)
    expect(q.answer).toBe(yes ? 0 : 1)
  }
  const m = screensMetrics([
    rec({ stimulus: { dual: false }, rt_ms: 600 }),
    rec({ stimulus: { dual: true }, rt_ms: 900, response: { answer: 0, on_target: 0.5 } }),
  ])
  expect(m).toEqual({ accuracy: 1, dual_task_cost: 300, on_target: 0.5 })
})

test('Sum & Keep sums are right or off, and letters are distinct', () => {
  for (const item of keepItems(mulberry32(2), 20)) {
    expect(new Set(item.letters).size).toBe(item.letters.length)
    for (const s of item.sums) {
      const [a, b, shown] = (s.text.match(/\d+/g) ?? []).map(Number)
      expect((a ?? 0) + (b ?? 0) === shown).toBe(s.right)
    }
  }
  expect(lettersOnly('f h-j')).toBe('FHJ')
})

test('Name Tags: distinct characters and names, and every option list holds the right name', () => {
  for (const item of tagItems(mulberry32(3), 10, 6)) {
    expect(new Set(item.people.map((p) => p.name)).size).toBe(6)
    expect(new Set(item.people.map((p) => JSON.stringify(p.look))).size).toBe(6)
    expect(item.questions).toHaveLength(6)
    for (const q of item.questions) {
      expect(q.options).toContain(q.person)
      expect(q.options).toHaveLength(4)
    }
  }
})

test('Maze Escape: the solution walks from the start to the exit through open rooms', () => {
  const step = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] } as const
  for (const deadEnds of [0.1, 0.5]) {
    const maze = makeMaze(mulberry32(4), 6, deadEnds)
    let [x, y] = [1, 1]
    for (const d of maze.solution) {
      const [dx, dy] = step[d]
      expect(maze.rows[y + dy]?.[x + dx]).toBe('.')
      x += 2 * dx
      y += 2 * dy
    }
    expect([x, y]).toEqual([11, 11])
    expect(maze.shortest).toBe(maze.solution.length)
  }
})

test('Fold & Punch: unfolding doubles the holes per fold, and options differ', () => {
  for (const folds of [1, 2, 3]) {
    for (const item of foldItems(mulberry32(5), 20, folds)) {
      expect(unfold(item.folds, item.punch)).toHaveLength(2 ** folds)
      const keys = item.options.map((o) => JSON.stringify([...o].sort()))
      expect(new Set(keys).size).toBe(4)
      expect(item.options[item.answer]).toEqual(unfold(item.folds, item.punch))
    }
  }
  const fold = { side: 'left' as const, region: [0, 0, 4, 4] as [number, number, number, number] }
  expect(unfold([fold], [2, 1])).toEqual([
    [2, 1],
    [1, 1],
  ])
})

test('Card Gamble: C and D pay off over time, A and B do not; a style with no right answer', () => {
  const item = gambleItem(mulberry32(6))
  const nets = item.decks.map((d) => d.slice(0, 10).reduce((n, c) => n + c.win - c.loss, 0))
  expect(nets).toEqual([-250, -250, 250, 250])
  expect(deckNet({ win: 50, losses: [250] })).toBe(250)
  const trials = [true, false, true, true].map((good, i) =>
    rec({ correct: null, response: { good, points: 2000 + i } }),
  )
  expect(gambleMetrics(trials)).toEqual({
    advantageous_choices: 2,
    late_advantageous: 2,
    points: 2003,
  })
})

test('Unusual Uses counts different ideas and original ones', () => {
  const thing = usesItems(mulberry32(7), 6).find((i) => i.thing.id === 'brick')?.thing
  if (!thing) throw new Error('no brick')
  const r = rate('build a wall\nDoorstop, doorstop; paperweight\n\nx', thing)
  expect(r.ideas).toEqual(['build a wall', 'Doorstop', 'paperweight'])
  expect(r.fluency).toBe(3)
  expect(r.originality).toBe(2)
  expect(rate(thing.examples.join(', '), thing).score).toBe(1)
  expect(rate('', thing).score).toBe(0)
})
