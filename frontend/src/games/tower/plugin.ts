import { parse } from 'yaml'

import { pick, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { medianRt, scored, taps } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { problems: number; extra_moves: number; deadline_ms: number }

/** Tower of London (Shallice, 1982): three pegs holding 3, 2 and 1 balls. A state lists the
 * balls on each peg from the bottom up. */
export type State = number[][]
export const CAPACITY = [3, 2, 1]
const COLOURS = ['red', 'green', 'blue']

const key = (s: State) => s.map((p) => p.join('')).join('|')

export function moves(s: State): [number, number][] {
  const out: [number, number][] = []
  s.forEach((from, i) => {
    if (from.length === 0) return
    s.forEach((to, j) => {
      if (i !== j && to.length < (CAPACITY[j] ?? 0)) out.push([i, j])
    })
  })
  return out
}

export function apply(s: State, [from, to]: [number, number]): State {
  const next = s.map((p) => [...p])
  const ball = next[from]?.pop()
  if (ball !== undefined) next[to]?.push(ball)
  return next
}

/** Shortest move list from `start` to every reachable state (breadth-first). */
export function shortestPaths(
  start: State,
): Map<string, { state: State; path: [number, number][] }> {
  const seen = new Map([[key(start), { state: start, path: [] as [number, number][] }]])
  const queue = [start]
  while (queue.length) {
    const s = queue.shift() as State
    const here = seen.get(key(s))
    for (const m of moves(s)) {
      const n = apply(s, m)
      if (!seen.has(key(n))) {
        seen.set(key(n), { state: n, path: [...(here?.path ?? []), m] })
        queue.push(n)
      }
    }
  }
  return seen
}

export interface TowerProblem {
  start: State
  goal: State
  min_moves: number
  solution: [number, number][]
}

export function makeItems(rng: Rng, count: number, minMoves: number): TowerProblem[] {
  const start: State = [[0, 1], [2], []]
  const all = [...shortestPaths(start).values()]
  return Array.from({ length: count }, () => {
    const from = pick(rng, all).state
    const reach = [...shortestPaths(from).values()]
    const best = Math.max(...reach.map((r) => r.path.length).filter((n) => n <= minMoves))
    const goal = pick(
      rng,
      reach.filter((r) => r.path.length === best),
    )
    return { start: from, goal: goal.state, min_moves: best, solution: goal.path }
  })
}

function draw(s: State, testid?: string): { box: HTMLElement; pegs: HTMLButtonElement[] } {
  const box = el('div', 'tw-tower')
  const pegs = s.map((balls, i) => {
    const peg = button('', testid ? `${testid}-${String(i)}` : '', 'tw-peg')
    peg.setAttribute(
      'aria-label',
      `Peg ${String(i + 1)}: ${balls.map((b) => COLOURS[b]).join(', ') || 'empty'}`,
    )
    peg.style.height = `${String((CAPACITY[i] ?? 1) * 2.4 + 0.6)}rem`
    for (const b of balls) peg.append(el('span', `tw-ball is-${COLOURS[b] ?? 'red'}`))
    return peg
  })
  box.append(...pegs)
  return { box, pegs }
}

const TowerPlugin = makePlugin<TowerProblem>(
  'najma-tower',
  async ({ stage, item, practice, e2e }) => {
    const goalView = el('div', 'tw-goal')
    goalView.append(el('p', 'game-prompt', 'Make it look like this:'), draw(item.goal).box)
    const area = el('div', 'tw-area')
    stage.append(goalView, area)
    let state = item.start
    let held: number | null = null
    let made = 0
    let firstMove: number | null = null
    const limit = item.min_moves + config.extra_moves
    const goal = key(item.goal)
    const { box, pegs } = draw(state, 'peg')
    area.append(box)
    const redraw = () => {
      const fresh = draw(state).pegs
      pegs.forEach((peg, i) => {
        peg.replaceChildren(...(fresh[i]?.childNodes ?? []))
        peg.setAttribute('aria-label', fresh[i]?.getAttribute('aria-label') ?? '')
        peg.classList.toggle('is-held', i === held)
      })
    }
    await taps(
      pegs.map((element, i) => ({ element, key: String(i + 1) })),
      {
        keys: ['1', '2', '3'],
        deadlineMs: config.deadline_ms,
        onReady: () => {
          const clicks = item.solution.flatMap(([f, t]) => [`peg-${String(f)}`, `peg-${String(t)}`])
          markAnswer(stage, e2e, `clicks:${clicks.join('|')}`)
        },
        onTap: (pressed, ms) => {
          const peg = Number(pressed) - 1
          if (held === null) {
            if ((state[peg]?.length ?? 0) > 0) held = peg
          } else if (peg === held) {
            held = null
          } else if ((state[peg]?.length ?? 0) < (CAPACITY[peg] ?? 0)) {
            state = apply(state, [held, peg])
            firstMove ??= ms
            made += 1
            held = null
          }
          redraw()
          return key(state) === goal || made >= limit
        },
      },
    )
    const solved = key(state) === goal
    const optimal = solved && made === item.min_moves
    if (practice) await practiceFeedback(stage, optimal)
    else await wait(300)
    return {
      stimulus: { start: item.start, goal: item.goal, min_moves: item.min_moves },
      response: { moves: made, solved },
      correct: optimal,
      rt_ms: firstMove,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const out: Record<string, number> = {
    optimal_share: s.length ? s.filter((t) => t.correct === true).length / s.length : 0,
  }
  const planning = medianRt(trials)
  if (planning !== null) out['planning_time_ms'] = planning
  return out
}

export const game: GameModule = {
  id: 'tower',
  name: 'Tower',
  instructions:
    'Move the balls so they match the picture, in as few moves as you can. Tap a peg to pick up its top ball, then tap where it goes. Plan first!',
  keysHint: 'Tap the pegs, or press 1, 2 and 3.',
  timeline({ spec, rng, e2e }) {
    const practice = Math.min(1, spec.practice_trials)
    const items = [
      ...makeItems(rng, practice, 2),
      ...makeItems(rng, config.problems, Math.round(spec.knobs['min_moves'] ?? 3)),
    ]
    return itemsToTimeline(TowerPlugin, items, practice, e2e)
  },
  metrics,
}
