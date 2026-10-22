import { parse } from 'yaml'

import { shuffle, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { path } from '../guide_the_robot/plugin'
import { medianRt, scored, taps } from '../shared/ask'
import { node, svg } from '../shared/svg'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { mazes: number; deadline_ms: number; move_limit: number }

type Dir = 'up' | 'down' | 'left' | 'right'
const DIRS: Record<Dir, [number, number]> = {
  up: [0, -1],
  down: [0, 1],
  left: [-1, 0],
  right: [1, 0],
}
const KEYS: Record<string, Dir> = {
  arrowup: 'up',
  arrowdown: 'down',
  arrowleft: 'left',
  arrowright: 'right',
}

export interface MazeItem {
  /** `#` wall, `.` open; rooms sit at odd coordinates. Start top left, exit bottom right. */
  rows: string[]
  shortest: number
  solution: Dir[]
}

/** A maze of `size` by `size` rooms (depth-first carving), then some dead ends opened into
 * loops: `deadEnds` is the share of dead ends kept. */
export function makeMaze(rng: Rng, size: number, deadEnds: number): MazeItem {
  const n = size * 2 + 1
  const grid = Array.from({ length: n }, () => Array<string>(n).fill('#'))
  const open = (x: number, y: number) => {
    const row = grid[y]
    if (row) row[x] = '.'
  }
  const isOpen = (x: number, y: number) => grid[y]?.[x] === '.'
  const inside = (x: number, y: number) => x > 0 && y > 0 && x < n - 1 && y < n - 1
  open(1, 1)
  const stack: [number, number][] = [[1, 1]]
  while (stack.length) {
    const [x, y] = stack[stack.length - 1] as [number, number]
    const next = shuffle(rng, Object.values(DIRS)).find(
      ([dx, dy]) => inside(x + 2 * dx, y + 2 * dy) && !isOpen(x + 2 * dx, y + 2 * dy),
    )
    if (!next) {
      stack.pop()
      continue
    }
    open(x + next[0], y + next[1])
    open(x + 2 * next[0], y + 2 * next[1])
    stack.push([x + 2 * next[0], y + 2 * next[1]])
  }
  for (let y = 1; y < n; y += 2) {
    for (let x = 1; x < n; x += 2) {
      const ways = Object.values(DIRS).filter(([dx, dy]) => isOpen(x + dx, y + dy))
      if (ways.length !== 1 || rng() < deadEnds) continue
      const wall = shuffle(rng, Object.values(DIRS)).find(
        ([dx, dy]) => !isOpen(x + dx, y + dy) && inside(x + 2 * dx, y + 2 * dy),
      )
      if (wall) open(x + wall[0], y + wall[1])
    }
  }
  const walls = grid.flatMap((row, y) =>
    row.flatMap((c, x) => (c === '#' ? [[x, y] as [number, number]] : [])),
  )
  const steps = path(n, walls, [1, 1], [n - 2, n - 2]) ?? []
  // Each room-to-room move is two grid steps in the same direction.
  const solution = steps.filter((_, i) => i % 2 === 0)
  return { rows: grid.map((r) => r.join('')), shortest: solution.length, solution }
}

function draw(item: MazeItem): { board: SVGSVGElement; player: SVGCircleElement } {
  const n = item.rows.length
  const board = svg(n, n, 'A maze. You start top left; the exit is bottom right.')
  item.rows.forEach((row, y) => {
    for (let x = 0; x < n; x++)
      if (row[x] === '#')
        board.append(node('rect', { x, y, width: 1, height: 1, fill: 'currentColor' }))
  })
  board.append(node('rect', { x: n - 2, y: n - 2, width: 1, height: 1, class: 'me-exit' }))
  const player = node('circle', { cx: 1.5, cy: 1.5, r: 0.38, class: 'me-player' })
  board.append(player)
  return { board, player }
}

const MazePlugin = makePlugin<MazeItem>(
  'lodestar-maze-escape',
  async ({ stage, item, practice, e2e }) => {
    const n = item.rows.length
    const { board, player } = draw(item)
    board.classList.add('me-board')
    const pad = el('div', 'me-pad')
    const buttons = (['up', 'left', 'right', 'down'] as Dir[]).map((d) => {
      const b = button({ up: '▲', down: '▼', left: '◀', right: '▶' }[d], `move-${d}`, `me-${d}`)
      b.setAttribute('aria-label', `Move ${d}`)
      return b
    })
    pad.append(...buttons)
    stage.append(board, pad)
    let at: [number, number] = [1, 1]
    let moves = 0
    let firstMove: number | null = null
    const exit = (p: [number, number]) => p[0] === n - 2 && p[1] === n - 2
    const limit = item.shortest * config.move_limit + 10
    await taps(
      buttons.map((element) => ({ element, key: element.dataset['testid']?.slice(5) ?? '' })),
      {
        keys: Object.keys(KEYS),
        deadlineMs: config.deadline_ms,
        onReady: () => {
          markAnswer(stage, e2e, `clicks:${item.solution.map((d) => `move-${d}`).join('|')}`)
        },
        onTap: (key, ms) => {
          const [dx, dy] = DIRS[KEYS[key] ?? (key as Dir)]
          if (item.rows[at[1] + dy]?.[at[0] + dx] !== '.') return false
          at = [at[0] + 2 * dx, at[1] + 2 * dy]
          firstMove ??= ms
          moves += 1
          player.setAttribute('cx', String(at[0] + 0.5))
          player.setAttribute('cy', String(at[1] + 0.5))
          return exit(at) || moves >= limit
        },
      },
    )
    const escaped = exit(at)
    const score = escaped ? item.shortest / moves : 0
    if (practice) await practiceFeedback(stage, escaped && moves === item.shortest)
    else await wait(300)
    return {
      stimulus: { rooms: (n - 1) / 2, shortest: item.shortest },
      response: { moves, escaped, extra_moves: escaped ? moves - item.shortest : null, score },
      correct: escaped,
      rt_ms: firstMove,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const out = scored(trials).filter((t) => t.correct === true)
  const extra = out.map((t) => Number(t.response?.['extra_moves'] ?? 0))
  const result: Record<string, number> = {
    escaped: out.length,
    extra_moves: extra.length ? extra.reduce((a, b) => a + b, 0) / extra.length : 0,
  }
  const planning = medianRt(trials)
  if (planning !== null) result['planning_time_ms'] = planning
  return result
}

export const game: GameModule = {
  id: 'maze_escape',
  name: 'Maze Escape',
  instructions:
    'Get from the top left to the exit at the bottom right in as few moves as you can. Plan your way first!',
  keysHint: 'Arrow keys, or tap the arrows.',
  timeline({ spec, rng, e2e }) {
    const practice = Math.min(1, spec.practice_trials)
    const size = Math.round(spec.knobs['size'] ?? 7)
    const deadEnds = spec.knobs['dead_ends'] ?? 0.3
    const items = [
      ...Array.from({ length: practice }, () => makeMaze(rng, 3, deadEnds)),
      ...Array.from({ length: config.mazes }, () => makeMaze(rng, size, deadEnds)),
    ]
    return itemsToTimeline(MazePlugin, items, practice, e2e)
  },
  metrics,
}
