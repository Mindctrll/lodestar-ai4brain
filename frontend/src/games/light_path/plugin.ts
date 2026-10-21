import { parse } from 'yaml'

import { type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, wait, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

interface Config {
  sequences: number
  blocks: [number, number][]
}
const config = parse(rawConfig) as Config

export interface PathItem {
  sequence: number[]
  backwards: boolean
  speed_ms: number
}

export function makeItems(
  rng: Rng,
  count: number,
  length: number,
  speed: number,
  backwards: boolean,
): PathItem[] {
  return Array.from({ length: count }, () => {
    const sequence: number[] = []
    while (sequence.length < length) {
      const next = Math.floor(rng() * config.blocks.length)
      if (next !== sequence[sequence.length - 1]) sequence.push(next)
    }
    return { sequence, backwards, speed_ms: speed }
  })
}

export function expected(item: PathItem): number[] {
  return item.backwards ? [...item.sequence].reverse() : item.sequence
}

const PathPlugin = makePlugin<PathItem>(
  'najma-light-path',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const board = el('div', 'lp-board')
    const blocks = config.blocks.map(([x, y], i) => {
      const b = button('', `block-${String(i)}`, 'lp-block')
      b.style.left = `${String(x)}%`
      b.style.top = `${String(y)}%`
      b.setAttribute('aria-label', `Square ${String(i + 1)}`)
      b.disabled = true
      return b
    })
    board.append(...blocks)
    const note = el(
      'p',
      'muted',
      item.backwards ? 'Watch, then tap them backwards.' : 'Watch, then tap them in order.',
    )
    const done = button('Done', 'path-done')
    done.disabled = true
    stage.append(note, board, done)
    await wait(500)
    for (const index of item.sequence) {
      blocks[index]?.classList.add('is-lit')
      await wait(item.speed_ms * 0.7)
      blocks[index]?.classList.remove('is-lit')
      await wait(item.speed_ms * 0.3)
    }
    const tapped: number[] = []
    const started = performance.now()
    for (const [i, b] of blocks.entries()) {
      b.disabled = false
      b.addEventListener('click', () => {
        tapped.push(i)
        b.classList.add('is-tapped')
        setTimeout(() => {
          b.classList.remove('is-tapped')
        }, 150)
      })
    }
    done.disabled = false
    const want = expected(item)
    await waitForResponse(jsPsych, {
      keys: ['enter'],
      targets: [{ element: done, key: 'enter' }],
      deadlineMs: 20_000,
      onReady: () => {
        markAnswer(
          stage,
          e2e,
          `clicks:${[...want.map((i) => `block-${String(i)}`), 'path-done'].join('|')}`,
        )
      },
    })
    const correct = tapped.length === want.length && tapped.every((v, i) => v === want[i])
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: { tapped },
      correct,
      rt_ms: performance.now() - started,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  const length = (scored[0]?.stimulus['sequence'] as number[] | undefined)?.length ?? 0
  return {
    accuracy: scored.length ? scored.filter((t) => t.correct === true).length / scored.length : 0,
    sequence_length: length,
  }
}

export const game: GameModule = {
  id: 'light_path',
  name: 'Light Path',
  instructions: 'Squares light up one at a time. Then tap them in the same order and press Done.',
  keysHint: 'Tap or click the squares; Enter for Done.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.sequences,
      Math.round(spec.knobs['sequence_length'] ?? 4),
      spec.knobs['speed_ms'] ?? 900,
      (spec.knobs['backwards'] ?? 0) >= 0.5,
    )
    return itemsToTimeline(PathPlugin, items, Math.min(spec.practice_trials, 1), e2e)
  },
  metrics,
}
