import { parse } from 'yaml'

import { pick, shuffle, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, choose, medianRt } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as {
  trials: number
  deadline_ms: number
  facts: [string, string][]
}

export const ANSWERS = ['Yes', 'No', 'Can’t tell'] as const

export interface LockItem {
  premises: string[]
  question: string
  /** Index into ANSWERS. */
  answer: number
  form: 'forward' | 'backward' | 'affirm_consequent' | 'deny_antecedent'
  deadline_ms: number
}

/** A chain of if-then rules plus one fact, then a question. Valid forward and backward chains
 * have a definite answer; the two classic fallacies (affirming the consequent, denying the
 * antecedent) can't be told. Kept in step with `cli/games.py`. */
export function makeItems(rng: Rng, count: number, premises: number): LockItem[] {
  const links = Math.max(1, premises - 1)
  return Array.from({ length: count }, () => {
    const facts = shuffle(rng, config.facts).slice(0, links + 1)
    const rules = facts.slice(0, -1).map(([, yes], i) => {
      const next = facts[i + 1] ?? facts[0]
      return `If ${yes}, then ${next?.[1] ?? ''}.`
    })
    const first = facts[0] ?? ['', '']
    const last = facts[facts.length - 1] ?? ['', '']
    const form = pick(rng, ['forward', 'backward', 'affirm_consequent', 'deny_antecedent'] as const)
    const [fact, question, answer] = {
      forward: [`${cap(first[1])}.`, `Is it true that ${last[1]}?`, 0],
      backward: [`${cap(last[0])}.`, `Is it true that ${first[1]}?`, 1],
      affirm_consequent: [`${cap(last[1])}.`, `Is it true that ${first[1]}?`, 2],
      deny_antecedent: [`${cap(first[0])}.`, `Is it true that ${last[1]}?`, 2],
    }[form] as [string, string, number]
    return {
      premises: [...shuffle(rng, rules), fact],
      question,
      answer,
      form,
      deadline_ms: config.deadline_ms,
    }
  })
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

const LockPlugin = makePlugin<LockItem>(
  'najma-logic-lock',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const list = el('ul', 'll-premises')
    list.append(...item.premises.map((p) => el('li', '', p)))
    stage.append(list, el('p', 'game-prompt', item.question))
    const { index, rt } = await choose(jsPsych, stage, e2e, [...ANSWERS], item.answer, {
      keys: ['1', '2', '3'],
      deadlineMs: item.deadline_ms,
    })
    const correct = index === item.answer
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: index === null ? null : { answer: ANSWERS[index] },
      correct,
      rt_ms: rt,
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const out: Record<string, number> = { accuracy: accuracy(trials) }
  const rt = medianRt(trials)
  if (rt !== null) out['median_rt_ms'] = rt
  return out
}

export const game: GameModule = {
  id: 'logic_lock',
  name: 'Logic Lock',
  instructions:
    'Read the rules and the fact, then answer: Yes, No, or Can’t tell. Use only what’s written, not what you’d expect.',
  keysHint: 'Keys 1, 2 and 3, or tap an answer.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      Math.round(spec.knobs['premises'] ?? 2),
    )
    return itemsToTimeline(LockPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
