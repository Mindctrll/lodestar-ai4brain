import { parse } from 'yaml'

import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { drawCell, type CellSpec } from '../shared/svg'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { deadline_ms: number; option_keys: string[] }

export interface Puzzle {
  grid: CellSpec[]
  options: CellSpec[]
  answer: number
  rules: { attribute: string; kind: string }[]
  hints: string[]
}

const PuzzlePlugin = makePlugin<Puzzle>(
  'lodestar-pattern-gap',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const grid = el('div', 'pg-grid')
    for (const cell of item.grid) {
      const box = el('div', 'pg-cell')
      box.append(drawCell(cell))
      grid.append(box)
    }
    grid.append(el('div', 'pg-cell pg-missing', '?'))
    const hintBox = el('p', 'pg-hint')
    hintBox.setAttribute('aria-live', 'polite')
    let hintLevel = 0
    const hintButton = button('Hint', 'hint')
    hintButton.addEventListener('click', () => {
      if (hintLevel < item.hints.length) {
        hintBox.textContent = item.hints[hintLevel] ?? ''
        hintLevel += 1
      }
      if (hintLevel >= item.hints.length) hintButton.disabled = true
    })
    const options = el('div', 'pg-options')
    const buttons = item.options.map((cell, i) => {
      const b = button('', `option-${String(i)}`, 'pg-option')
      b.append(
        drawCell(cell, 70),
        el('span', 'pg-letter', (config.option_keys[i] ?? '').toUpperCase()),
      )
      return b
    })
    options.append(...buttons)
    stage.append(grid, hintButton, hintBox, options)
    const response = await waitForResponse(jsPsych, {
      keys: config.option_keys.slice(0, item.options.length),
      targets: buttons.map((element, i) => ({ element, key: config.option_keys[i] ?? '' })),
      deadlineMs: config.deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, `click:option-${String(item.answer)}`)
      },
    })
    const chosen = response.key === null ? null : config.option_keys.indexOf(response.key)
    const correct = chosen === item.answer
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { rules: item.rules.length, answer: item.answer },
      response: chosen === null ? null : { option: chosen },
      correct,
      rt_ms: response.rt,
      hint_level: hintLevel,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  return {
    accuracy: scored.length ? scored.filter((t) => t.correct === true).length / scored.length : 0,
    hints_used: scored.reduce((sum, t) => sum + (t.hint_level ?? 0), 0),
  }
}

export const game: GameModule = {
  id: 'pattern_gap',
  name: 'Pattern Gap',
  instructions:
    'The last cell of the grid is missing. Pick the option that completes the pattern. Ask for a hint if you want one.',
  keysHint: 'A to E, or tap an option.',
  timeline({ spec, e2e }) {
    const puzzles = (spec.content?.['puzzles'] as Puzzle[] | undefined) ?? []
    if (puzzles.length === 0) throw new Error('Pattern Gap needs puzzles from the server')
    return itemsToTimeline(PuzzlePlugin, puzzles, Math.min(spec.practice_trials, 1), e2e)
  },
  metrics,
}
