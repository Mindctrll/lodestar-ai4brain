import { parse } from 'yaml'

import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { deadline_ms: number }

export interface MistakePuzzle {
  question: string
  steps: { text: string }[]
  has_error: boolean
  error_step: number | null
}

const MistakePlugin = makePlugin<MistakePuzzle>(
  'lodestar-spot-the-mistake',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    stage.append(el('p', 'sm-question', item.question))
    stage.append(el('p', 'muted', "Lodestar's working. Which step is wrong, if any?"))
    const list = el('ol', 'sm-steps')
    const buttons = item.steps.map((step, i) => {
      const b = button(step.text, `step-${String(i)}`, 'sm-step')
      const li = el('li')
      li.append(b)
      list.append(li)
      return b
    })
    const allRight = button('All steps are right', 'step-none', 'sm-none')
    stage.append(list, allRight)
    const response = await waitForResponse(jsPsych, {
      keys: [],
      targets: [
        ...buttons.map((element, i) => ({ element, key: String(i) })),
        { element: allRight, key: 'none' },
      ],
      deadlineMs: config.deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, `click:step-${item.has_error ? String(item.error_step) : 'none'}`)
      },
    })
    const flagged = response.key === null || response.key === 'none' ? null : Number(response.key)
    const correct =
      response.key !== null && (item.has_error ? flagged === item.error_step : flagged === null)
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: {
        has_error: item.has_error,
        error_step: item.error_step,
        steps: item.steps.length,
      },
      response: response.key === null ? null : { flagged },
      correct,
      rt_ms: response.rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  const rate = (hasError: boolean) => {
    const group = scored.filter((t) => t.stimulus['has_error'] === hasError)
    return group.length ? group.filter((t) => t.correct === true).length / group.length : null
  }
  const parts = [rate(true), rate(false)].filter((x): x is number => x !== null)
  return {
    balanced_accuracy: parts.length ? parts.reduce((a, b) => a + b, 0) / parts.length : 0,
    accuracy: scored.length ? scored.filter((t) => t.correct === true).length / scored.length : 0,
  }
}

export const game: GameModule = {
  id: 'spot_the_mistake',
  name: "Spot the AI's Mistake",
  instructions:
    "Lodestar will solve a few puzzles step by step. Some solutions have one mistake, some don't. Find the wrong step, or say they're all right.",
  keysHint: 'Tap a step, or All steps are right.',
  timeline({ spec, e2e }) {
    const puzzles = (spec.content?.['puzzles'] as MistakePuzzle[] | undefined) ?? []
    if (puzzles.length === 0) throw new Error("Spot the AI's Mistake needs puzzles from the server")
    return itemsToTimeline(MistakePlugin, puzzles, 0, e2e)
  },
  metrics,
}
