import { parse } from 'yaml'

import { randInt, shuffle, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { trials: number; symbols: string[] }

export interface CodeItem {
  key: string[] // symbol for digit 1, 2, ...
  target: number // index into key
  deadline_ms: number
}

export function makeItems(rng: Rng, count: number, size: number, deadline: number): CodeItem[] {
  const key = shuffle(rng, config.symbols).slice(0, size)
  return Array.from({ length: count }, () => ({
    key,
    target: randInt(rng, 0, size - 1),
    deadline_ms: deadline,
  }))
}

const CodePlugin = makePlugin<CodeItem>(
  'lodestar-symbol-code',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const keyRow = el('div', 'sc-key')
    const cells = item.key.map((symbol, i) => {
      const b = button('', `digit-${String(i + 1)}`, 'sc-pair')
      b.append(el('span', 'sc-symbol', symbol), el('span', 'sc-digit', String(i + 1)))
      return b
    })
    keyRow.append(...cells)
    const target = el('div', 'sc-target', item.key[item.target] ?? '?')
    target.setAttribute('aria-label', 'Symbol to code')
    stage.append(keyRow, target)
    const digits = item.key.map((_, i) => String(i + 1))
    const response = await waitForResponse(jsPsych, {
      keys: digits,
      targets: cells.map((element, i) => ({ element, key: String(i + 1) })),
      deadlineMs: item.deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, `key:${String(item.target + 1)}`)
      },
    })
    const correct = response.key === String(item.target + 1)
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: response.key === null ? null : { digit: Number(response.key) },
      correct,
      rt_ms: response.rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  const right = scored.filter((t) => t.correct === true).length
  const ms = scored.reduce((sum, t) => sum + (t.rt_ms ?? (t.stimulus['deadline_ms'] as number)), 0)
  return {
    accuracy: scored.length ? right / scored.length : 0,
    items_per_min: ms > 0 ? right / (ms / 60_000) : 0,
  }
}

export const game: GameModule = {
  id: 'symbol_code',
  name: 'Symbol Code',
  instructions: 'The key pairs each symbol with a number. When a symbol appears, press its number.',
  keysHint: 'Number keys, or tap the symbol on the key.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      Math.round(spec.knobs['key_size'] ?? 6),
      spec.knobs['deadline_ms'] ?? 2000,
    )
    return itemsToTimeline(CodePlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
