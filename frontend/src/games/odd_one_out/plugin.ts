import { parse } from 'yaml'

import { median, randInt, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

interface Config {
  trials: number
  deadline_ms: number
  pairs: [string, string][]
}
const config = parse(rawConfig) as Config

export interface SearchItem {
  set_size: number
  target: number
  distractor: string
  odd: string
  deadline_ms: number
}

const GLYPH: Record<string, string> = { square: '■', circle: '●' }
const show = (g: string) => GLYPH[g] ?? g

export function makeItems(
  rng: Rng,
  count: number,
  setSize: number,
  similarity: number,
): SearchItem[] {
  const pair = config.pairs[
    Math.min(config.pairs.length - 1, Math.floor(similarity * config.pairs.length))
  ] ?? ['square', 'circle']
  const half = Math.max(2, Math.round(setSize / 2))
  return Array.from({ length: count }, (_, i) => {
    const size = i % 2 === 0 ? setSize : half // mixing sizes gives the search slope
    return {
      set_size: size,
      target: randInt(rng, 0, size - 1),
      distractor: pair[0],
      odd: pair[1],
      deadline_ms: config.deadline_ms,
    }
  })
}

const SearchPlugin = makePlugin<SearchItem>(
  'lodestar-odd-one-out',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const grid = el('div', 'oo-grid')
    grid.style.gridTemplateColumns = `repeat(${String(Math.ceil(Math.sqrt(item.set_size)))}, 2.75rem)`
    const cells = Array.from({ length: item.set_size }, (_, i) => {
      const b = button(
        show(i === item.target ? item.odd : item.distractor),
        `item-${String(i)}`,
        'oo-item',
      )
      b.setAttribute('aria-label', `Item ${String(i + 1)}`)
      return b
    })
    grid.append(...cells)
    stage.append(grid)
    const response = await waitForResponse(jsPsych, {
      keys: [],
      targets: cells.map((element, i) => ({ element, key: String(i) })),
      deadlineMs: item.deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, `click:item-${String(item.target)}`)
      },
    })
    const correct = response.key === String(item.target)
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: response.key === null ? null : { index: Number(response.key) },
      correct,
      rt_ms: response.rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  const out: Record<string, number> = {
    accuracy: scored.length ? scored.filter((t) => t.correct === true).length / scored.length : 0,
  }
  const sizes = [...new Set(scored.map((t) => t.stimulus['set_size'] as number))].sort(
    (a, b) => a - b,
  )
  const small = sizes[0]
  const big = sizes[sizes.length - 1]
  if (small !== undefined && big !== undefined && big > small) {
    const rt = (n: number) =>
      median(
        scored
          .filter((t) => t.correct === true && t.rt_ms !== null && t.stimulus['set_size'] === n)
          .map((t) => t.rt_ms as number),
      )
    const a = rt(small)
    const b = rt(big)
    if (a !== null && b !== null) out['search_slope_ms_per_item'] = (b - a) / (big - small)
  }
  return out
}

export const game: GameModule = {
  id: 'odd_one_out',
  name: 'Odd One Out',
  instructions: 'One item in the crowd is different. Find it and tap it as fast as you can.',
  keysHint: 'Tap or click the item; Tab and Enter also work.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      Math.round(spec.knobs['set_size'] ?? 8),
      spec.knobs['similarity'] ?? 0.2,
    )
    return itemsToTimeline(SearchPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
