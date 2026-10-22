import { parse } from 'yaml'

import { randInt, shuffle, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { scored, taps } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as {
  problems: number
  attempts: number
  wall_share: number
  deadline_ms: number
  colours: [string, string]
}

type Cell = [number, number]
const DIRS = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] } as const
type Dir = keyof typeof DIRS

export interface RobotItem {
  size: number
  walls: Cell[]
  start: Cell
  stars: Cell[]
  /** Which star Lodestar means; on ambiguous items it doesn't say which. */
  intended: number
  ambiguous: boolean
  shortest: number
  solution: string
}

const same = (a: Cell, b: Cell) => a[0] === b[0] && a[1] === b[1]

/** Breadth-first shortest path as a list of steps, or null when walled off. */
export function path(size: number, walls: Cell[], from: Cell, to: Cell): Dir[] | null {
  const blocked = new Set(walls.map(([x, y]) => `${String(x)},${String(y)}`))
  const prev = new Map<string, [string, Dir] | null>([[from.join(','), null]])
  const queue: Cell[] = [from]
  while (queue.length) {
    const here = queue.shift() as Cell
    if (same(here, to)) break
    for (const [d, [dx, dy]] of Object.entries(DIRS) as [Dir, readonly [number, number]][]) {
      const next: Cell = [here[0] + dx, here[1] + dy]
      const k = next.join(',')
      if (next[0] < 0 || next[1] < 0 || next[0] >= size || next[1] >= size) continue
      if (blocked.has(k) || prev.has(k)) continue
      prev.set(k, [here.join(','), d])
      queue.push(next)
    }
  }
  if (!prev.has(to.join(','))) return null
  const steps: Dir[] = []
  let k = to.join(',')
  for (let link = prev.get(k); link; link = prev.get(k)) {
    steps.unshift(link[1])
    k = link[0]
  }
  return steps
}

/** "right, right, down" becomes "right 2, down 1". */
export function describe(steps: Dir[]): string {
  const parts: string[] = []
  let i = 0
  while (i < steps.length) {
    let n = 1
    while (steps[i + n] === steps[i]) n += 1
    parts.push(`${steps[i] ?? ''} ${String(n)}`)
    i += n
  }
  return parts.join(', ')
}

export function makeItems(rng: Rng, count: number, size: number, ambiguity: number): RobotItem[] {
  const ambiguous = shuffle(
    rng,
    Array.from({ length: count }, (_, i) => i < Math.max(1, Math.round(count * ambiguity))),
  )
  return Array.from({ length: count }, (_, n) => {
    for (;;) {
      const cells: Cell[] = []
      for (let x = 0; x < size; x++) for (let y = 0; y < size; y++) cells.push([x, y])
      const [start, a, b, ...rest] = shuffle(rng, cells) as [Cell, Cell, Cell, ...Cell[]]
      const walls = rest.filter(() => rng() < config.wall_share)
      const intended = randInt(rng, 0, 1)
      const target = intended === 0 ? a : b
      const route = path(size, walls, start, target)
      const other = path(size, walls, start, intended === 0 ? b : a)
      if (!route || !other || route.length < 2) continue
      return {
        size,
        walls,
        start,
        stars: [a, b],
        intended,
        ambiguous: ambiguous[n] ?? false,
        shortest: route.length,
        solution: describe(route),
      }
    }
  })
}

/** Instructions like "up 2, right 3" (or "u2 r3"). A direction without a number is too vague
 * for the robot, which is the point: vague instructions fail. */
export function parseInstructions(text: string): { steps: Dir[]; vague: boolean } {
  const steps: Dir[] = []
  let vague = false
  const re = /\b(up|down|left|right|u|d|l|r)\b\s*(\d+)?/gi
  for (const m of text.toLowerCase().matchAll(re)) {
    const word = m[1] ?? ''
    const dir = (Object.keys(DIRS) as Dir[]).find((d) => d.startsWith(word.charAt(0))) ?? 'up'
    if (m[2] === undefined) vague = true
    for (let i = 0; i < Number(m[2] ?? 0); i++) steps.push(dir)
  }
  return { steps, vague: vague || steps.length === 0 }
}

export function run(item: RobotItem, steps: Dir[]): { at: Cell; bumped: boolean } {
  let at = item.start
  for (const d of steps) {
    const next: Cell = [at[0] + DIRS[d][0], at[1] + DIRS[d][1]]
    const off = next[0] < 0 || next[1] < 0 || next[0] >= item.size || next[1] >= item.size
    if (off || item.walls.some((w) => same(w, next))) return { at, bumped: true }
    at = next
  }
  return { at, bumped: false }
}

function drawMaze(item: RobotItem, robot: Cell): HTMLElement {
  const grid = el('div', 'gr-grid')
  grid.style.gridTemplateColumns = `repeat(${String(item.size)}, 2rem)`
  for (let y = 0; y < item.size; y++)
    for (let x = 0; x < item.size; x++) {
      const here: Cell = [x, y]
      const star = item.stars.findIndex((s) => same(s, here))
      const text = same(robot, here) ? '🤖' : star >= 0 ? '★' : ''
      const cell = el(
        'span',
        `gr-cell${item.walls.some((w) => same(w, here)) ? ' is-wall' : ''}`,
        text,
      )
      if (star >= 0 && !same(robot, here))
        cell.classList.add(`is-${config.colours[star] ?? 'gold'}`)
      grid.append(cell)
    }
  return grid
}

const RobotPlugin = makePlugin<RobotItem>(
  'lodestar-guide-the-robot',
  async ({ stage, item, practice, e2e }) => {
    const colour = config.colours[item.intended] ?? 'gold'
    const board = el('div', 'gr-board')
    board.append(drawMaze(item, item.start))
    const say = el(
      'p',
      'game-prompt',
      item.ambiguous ? 'Take the robot to the star.' : `Take the robot to the ${colour} star.`,
    )
    const reply = el('p', 'gr-reply')
    reply.setAttribute('aria-live', 'polite')
    const input = el('input', 'type-input')
    input.dataset['testid'] = 'recall-input'
    input.setAttribute('aria-label', 'Instructions, like: up 2, right 3')
    input.placeholder = 'Instructions, like: up 2, right 3'
    const ask = button('Ask Lodestar', 'robot-ask')
    const go = button('Run', 'recall-done')
    const row = el('div', 'type-row')
    row.append(input, go, ask)
    stage.append(say, board, reply, row)
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') go.dispatchEvent(new PointerEvent('pointerdown'))
    })
    let asked = false
    let askedFirst = false
    let attempts = 0
    let solved = false
    let firstFailed = false
    let optimal = false
    const typed: string[] = []
    const started = performance.now()
    await taps(
      [
        { element: ask, key: 'ask' },
        { element: go, key: 'run' },
      ],
      {
        deadlineMs: config.deadline_ms,
        onReady: () => {
          markAnswer(
            stage,
            e2e,
            `${item.ambiguous ? 'click:robot-ask >> ' : ''}type:${item.solution}`,
          )
          input.focus()
        },
        onTap: (key) => {
          if (key === 'ask') {
            if (!asked && attempts === 0) askedFirst = true
            asked = true
            reply.textContent = item.ambiguous
              ? `Lodestar: I mean the ${colour} star.`
              : `Lodestar: The ${colour} one, like I said.`
            return false
          }
          attempts += 1
          typed.push(input.value)
          const { steps, vague } = parseInstructions(input.value)
          const { at, bumped } = run(item, steps)
          board.replaceChildren(drawMaze(item, at))
          const target = item.stars[item.intended] ?? item.start
          solved = !vague && !bumped && same(at, target)
          if (solved) {
            optimal = steps.length === item.shortest
            reply.textContent = 'Lodestar: Made it!'
            return true
          }
          if (attempts === 1) firstFailed = true
          reply.textContent = vague
            ? 'Lodestar: The robot needs a number of steps for each direction, like "up 2".'
            : bumped
              ? 'Lodestar: The robot bumped into something. Edit your instructions and try again.'
              : 'Lodestar: That’s not the star I meant. Try again.'
          if (attempts >= config.attempts) return true
          window.setTimeout(() => {
            board.replaceChildren(drawMaze(item, item.start))
          }, 900)
          return false
        },
      },
    )
    await wait(practice ? 900 : 500)
    return {
      stimulus: {
        size: item.size,
        ambiguous: item.ambiguous,
        shortest: item.shortest,
        intended: colour,
      },
      response: {
        asked,
        asked_first: askedFirst,
        attempts,
        first_failed: firstFailed,
        solved,
        optimal,
        instructions: typed,
      },
      correct: solved,
      rt_ms: performance.now() - started,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const r = (k: string) => s.filter((t) => t.response?.[k] === true).length
  return {
    optimal_share: s.length ? r('optimal') / s.length : 0,
    clarifications: r('asked'),
    retries: s.reduce((n, t) => n + Math.max(0, Number(t.response?.['attempts'] ?? 1) - 1), 0),
  }
}

export const game: GameModule = {
  id: 'guide_the_robot',
  name: 'Guide the Robot',
  instructions:
    'Type instructions to move the robot to the star Lodestar means, like "up 2, right 3". Walls block the way. If something isn’t clear, ask Lodestar first.',
  keysHint: 'Type, then Enter or Run. Ask Lodestar when unsure.',
  timeline({ spec, rng, e2e }) {
    const practice = Math.min(1, spec.practice_trials)
    const size = Math.round(spec.knobs['maze_size'] ?? 5)
    const items = [
      ...makeItems(rng, practice, Math.min(size, 4), 0).map((i) => ({ ...i, ambiguous: false })),
      ...makeItems(rng, config.problems, size, Math.max(0.25, spec.knobs['ambiguity'] ?? 0.25)),
    ]
    return itemsToTimeline(RobotPlugin, items, practice, e2e)
  },
  metrics,
}
