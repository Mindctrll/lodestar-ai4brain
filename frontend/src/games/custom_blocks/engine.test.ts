import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { initJsPsych, type JsPsych } from 'jspsych'
import { parse } from 'yaml'

import type { ExerciseSpec } from '../../api/types'
import { mulberry32 } from '../../lib/rng'
import type { TrialRecord } from '../../taskhost/types'
import { buildItems, config, ruleKey, scoreRecall, type BlockItem, type Recipe } from './engine'
import { game } from './plugin'

interface Row {
  request: string
  valid: boolean
  recipe: unknown
  served: Recipe | null
}

// Written by `uv run python -m backend.generation.recipe_samples` (WP3.7 "Done when").
const ROWS = parse(
  readFileSync(join(import.meta.dirname, '../../../../tests/fixtures/custom_recipes.yaml'), 'utf8'),
) as Row[]
// What the server sends after validation: the recipe with its defaults filled in.
const recipeOf = (row: Row): Recipe => {
  if (!row.served) throw new Error(row.request)
  return row.served
}

const spec = (content: Recipe, seed: number): ExerciseSpec => ({
  round_id: 'r',
  game_id: 'custom_blocks',
  mode: 'train',
  target_p: 0.8,
  level: 0.5,
  difficulty_b: 0,
  knobs: {},
  seed,
  practice_trials: 0,
  duration_s: 180,
  reason: 'test',
  content,
  content_item_id: null,
  theme: null,
  track: null,
})

test('item pools match the sizes the server validates against', () => {
  // POOL in backend/generation/blocks.py
  const sizes = { digits: 10, letters: 20, words: 40, shapes: 8 }
  for (const [kind, size] of Object.entries(sizes)) {
    const pool = config.pools[kind as keyof typeof sizes]
    expect(pool).toHaveLength(size)
    expect(new Set(pool).size).toBe(size)
  }
})

test('every valid recipe of the 50 builds a playable timeline', () => {
  const valid = ROWS.filter((r) => r.valid)
  expect(ROWS).toHaveLength(50)
  expect(valid.length).toBeGreaterThanOrEqual(20)
  for (const [i, row] of valid.entries()) {
    const recipe = recipeOf(row)
    const timeline = game.timeline({ spec: spec(recipe, i), rng: mulberry32(i), e2e: false })
    expect(timeline).toHaveLength(recipe.steps.length * recipe.repeat)
    const items = timeline.map((t) => t['item'] as BlockItem)
    expect(buildItems(recipe, mulberry32(i))).toEqual(items) // replayable from the seed
    let shown: string[] = []
    for (const item of items) {
      switch (item.block) {
        case 'show_items':
          expect(item.items.length).toBeGreaterThanOrEqual(2)
          shown = item.items
          break
        case 'recall':
          expect(item.target).toEqual(shown)
          for (const t of item.target) expect(item.palette).toContain(t)
          expect(scoreRecall(item.kind, item.target, item.target).every(Boolean)).toBe(true)
          break
        case 'recognition': {
          expect(item.target).toEqual(shown)
          const seen = item.probes.filter((p) => p.seen).map((p) => p.item)
          expect(seen.sort()).toEqual([...shown].sort())
          for (const p of item.probes.filter((x) => !x.seen)) expect(shown).not.toContain(p.item)
          expect(item.probes).toHaveLength(2 * shown.length)
          break
        }
        case 'choice':
          expect(item.options).toContain(item.answer)
          break
        case 'rule':
          for (const t of item.trials) expect(['f', 'j']).toContain(ruleKey(t))
          break
        case 'react':
          expect(item.trials.some((t) => t.target)).toBe(true)
          break
        case 'distractor':
          if (item.task !== 'tapping') expect(item.problems).toHaveLength(item.seconds)
          break
        default:
          break
      }
    }
  }
})

test('a spec without a recipe is an error, not a crash', () => {
  const empty = { ...spec({} as Recipe, 1), content: null }
  expect(() => game.timeline({ spec: empty, rng: mulberry32(1), e2e: false })).toThrow()
})

test('rule keys and recall scoring', () => {
  expect(ruleKey({ n: 3, rule: 'odd_even' })).toBe('f')
  expect(ruleKey({ n: 8, rule: 'high_low' })).toBe('j')
  expect(scoreRecall('ordered', ['1', '2', '3'], ['1', '3', '2'])).toEqual([true, false, false])
  expect(scoreRecall('free', ['a', 'b', 'c'], ['c', 'a'])).toEqual([true, false, true])
})

test('metrics: accuracy over scored answers only', () => {
  const rec = (correct: boolean | null): TrialRecord => ({
    trial_index: 0,
    practice: false,
    stimulus: {},
    response: null,
    correct,
    rt_ms: 500,
  })
  expect(game.metrics([rec(true), rec(false), rec(null), rec(true)])['accuracy']).toBeCloseTo(2 / 3)
})

test('every valid recipe runs to the end in jsPsych, even with no answers', async () => {
  // Every block ends on its own clock, so fake timers can play each recipe through.
  vi.useFakeTimers({
    toFake: ['setTimeout', 'clearTimeout', 'requestAnimationFrame', 'performance'],
  })
  try {
    for (const [i, row] of ROWS.filter((r) => r.valid).entries()) {
      const display = document.createElement('div')
      document.body.append(display)
      const records: TrialRecord[] = []
      const done = { finished: false }
      const jsPsych = initJsPsych({
        display_element: display,
        on_data_update: (data: Record<string, unknown>) => {
          records.push(...((data['lodestar'] as TrialRecord[] | undefined) ?? []))
        },
        on_finish: () => {
          done.finished = true
        },
      })
      const timeline = game.timeline({
        spec: spec(recipeOf(row), i),
        rng: mulberry32(i),
        e2e: false,
      })
      const run = jsPsych.run(timeline as unknown as Parameters<JsPsych['run']>[0])
      for (let step = 0; step < 400 && !done.finished; step++)
        await vi.advanceTimersByTimeAsync(5_000)
      await run
      expect(done.finished, row.request).toBe(true)
      expect(records.length, row.request).toBeGreaterThan(0)
      // Nobody answered: only holding back for a decoy counts as right.
      const right = records.filter((r) => r.correct === true)
      expect(right.every((r) => r.stimulus['block'] === 'react' && !r.stimulus['target'])).toBe(
        true,
      )
      display.remove()
    }
  } finally {
    vi.useRealTimers()
  }
})
