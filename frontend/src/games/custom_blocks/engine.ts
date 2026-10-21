/** The block engine (docs/plan/08): a validated recipe becomes a list of timeline items, one
 * per block per repeat, with every random choice drawn from the round's seed. The server
 * (backend/generation/blocks.py) is the source of truth for what a valid recipe is; this file
 * only turns one into concrete stimuli. */
import { parse } from 'yaml'

import type { components } from '../../contracts/api'
import { pick, randInt, shuffle, type Rng } from '../../lib/rng'
import rawConfig from './config.yaml?raw'

type Schemas = components['schemas']
export type Recipe = Schemas['CustomGameContent']
export type Step = Recipe['steps'][number]
type PoolKind = 'digits' | 'letters' | 'words' | 'shapes'

export interface Config {
  pools: Record<PoolKind, string[]>
  recall_deadline_ms: number
  recognition_deadline_ms: number
  choice_deadline_ms: number
  rule_deadline_ms: number
  feedback_ms: number
}
export const config = parse(rawConfig) as Config

export type RuleName = Schemas['Rule']['rule']
export interface Problem {
  text: string
  holds: boolean
}

export type BlockItem = { title: string; round: number } & (
  | { block: 'show_items'; items: string[]; ms_each: number }
  | {
      block: 'distractor'
      task: Schemas['Distractor']['task']
      seconds: number
      problems: Problem[]
    }
  | { block: 'recall'; kind: 'ordered' | 'free'; target: string[]; palette: string[] }
  | { block: 'recognition'; target: string[]; probes: { item: string; seen: boolean }[] }
  | { block: 'choice'; question: string; options: string[]; answer: string }
  | { block: 'timer'; seconds: number }
  | { block: 'rule'; trials: { n: number; rule: RuleName }[] }
  | {
      block: 'react'
      deadline_ms: number
      trials: { stim: string; target: boolean; isi_ms: number }[]
    }
  | { block: 'feedback'; level: Schemas['Feedback']['level'] }
)

const NUMBERS = [1, 2, 3, 4, 6, 7, 8, 9]

function problem(rng: Rng, hard: boolean): Problem {
  const a = hard ? randInt(rng, 12, 49) : randInt(rng, 1, 9)
  const b = hard ? randInt(rng, 3, 9) : randInt(rng, 1, 9)
  const plus = hard ? rng() < 0.5 : true
  const right = plus ? a + b : a - b
  const holds = rng() < 0.5
  const shown = holds ? right : right + pick(rng, [-2, -1, 1, 2])
  return { text: `${String(a)} ${plus ? '+' : '−'} ${String(b)} = ${String(shown)}`, holds }
}

function drawItems(rng: Rng, spec: string | string[]): { items: string[]; kind: PoolKind | null } {
  if (Array.isArray(spec)) return { items: [...spec], kind: null }
  const [kind, count] = spec.split(':') as [PoolKind, string]
  const pool = config.pools[kind]
  const n = Number(count)
  if (kind === 'digits') return { items: Array.from({ length: n }, () => pick(rng, pool)), kind }
  return { items: shuffle(rng, pool).slice(0, n), kind }
}

function lures(rng: Rng, kind: PoolKind, shown: string[], n: number): string[] {
  return shuffle(
    rng,
    config.pools[kind].filter((x) => !shown.includes(x)),
  ).slice(0, n)
}

function expand(step: Step, rng: Rng, last: { items: string[]; kind: PoolKind | null }) {
  switch (step.block) {
    case 'show_items':
      return { block: 'show_items' as const, items: last.items, ms_each: step.ms_each }
    case 'distractor': {
      const count = step.task === 'tapping' ? 0 : step.seconds
      const hard = step.task === 'arithmetic:hard'
      const problems = Array.from({ length: count }, () => problem(rng, hard))
      return { block: 'distractor' as const, task: step.task, seconds: step.seconds, problems }
    }
    case 'recall': {
      const { items, kind } = last
      if (step.kind === 'recognition') {
        if (kind === null) throw new Error('recognition needs drawn items')
        const probes = shuffle(rng, [
          ...items.map((item) => ({ item, seen: true })),
          ...lures(rng, kind, items, items.length).map((item) => ({ item, seen: false })),
        ])
        return { block: 'recognition' as const, target: items, probes }
      }
      let palette: string[]
      if (kind === 'digits') palette = config.pools.digits
      else if (kind === null) palette = shuffle(rng, items)
      else palette = shuffle(rng, [...items, ...lures(rng, kind, items, items.length)])
      return { block: 'recall' as const, kind: step.kind, target: items, palette }
    }
    case 'choice':
      return { ...step, block: 'choice' as const }
    case 'timer':
      return { block: 'timer' as const, seconds: step.seconds }
    case 'rule': {
      const other: RuleName = step.rule === 'odd_even' ? 'high_low' : 'odd_even'
      const trials = Array.from({ length: step.trials }, (_, i) => ({
        n: pick(rng, NUMBERS),
        rule: step.switch_after && Math.floor(i / step.switch_after) % 2 === 1 ? other : step.rule,
      }))
      return { block: 'rule' as const, trials }
    }
    case 'react': {
      const decoys = step.distractors ?? []
      const trials = Array.from({ length: step.trials }, (_, i) => {
        const target = decoys.length === 0 || i === 0 || rng() < 0.5
        return {
          stim: target ? step.target : pick(rng, decoys),
          target,
          isi_ms: randInt(rng, 300, 800),
        }
      })
      return {
        block: 'react' as const,
        deadline_ms: step.deadline_ms,
        trials: shuffle(rng, trials),
      }
    }
    case 'feedback':
      return { block: 'feedback' as const, level: step.level }
  }
}

/** Every block of every repeat, in order. */
export function buildItems(recipe: Recipe, rng: Rng): BlockItem[] {
  const out: BlockItem[] = []
  const repeat = recipe.repeat
  for (let round = 0; round < repeat; round++) {
    let last: { items: string[]; kind: PoolKind | null } = { items: [], kind: null }
    for (const step of recipe.steps) {
      if (step.block === 'show_items') last = drawItems(rng, step.items)
      out.push({ title: recipe.title, round, ...expand(step, rng, last) })
    }
  }
  return out
}

/** The right key for a rule trial: F for odd or low, J for even or high. */
export function ruleKey(trial: { n: number; rule: RuleName }): 'f' | 'j' {
  if (trial.rule === 'odd_even') return trial.n % 2 === 1 ? 'f' : 'j'
  return trial.n < 5 ? 'f' : 'j'
}

/** Recall scoring: by position for ordered recall, by membership for free recall. */
export function scoreRecall(
  kind: 'ordered' | 'free',
  target: string[],
  answer: string[],
): boolean[] {
  if (kind === 'ordered') return target.map((t, i) => answer[i] === t)
  const given = new Set(answer)
  return target.map((t) => given.has(t))
}
