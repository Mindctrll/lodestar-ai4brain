import type { JsPsych } from 'jspsych'

import { median } from '../../lib/rng'
import {
  button,
  el,
  itemsToTimeline,
  makePlugin,
  markAnswer,
  type TrialOutcome,
} from '../../taskhost/plugin'
import { wait, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { buildItems, config, ruleKey, scoreRecall, type BlockItem, type Recipe } from './engine'

type Of<B extends BlockItem['block']> = Extract<BlockItem, { block: B }>
type Ctx = { jsPsych: JsPsych; stage: HTMLElement; e2e: boolean }

function row(...nodes: HTMLElement[]): HTMLElement {
  const r = el('div', 'sw-buttons')
  r.append(...nodes)
  return r
}

async function showItems(item: Of<'show_items'>, { stage }: Ctx): Promise<TrialOutcome[]> {
  const shown = el('div', 'ml-word')
  stage.append(shown)
  for (const x of item.items) {
    shown.textContent = x
    await wait(item.ms_each * 0.8)
    shown.textContent = ''
    await wait(item.ms_each * 0.2)
  }
  return []
}

async function distractor(
  item: Of<'distractor'>,
  { jsPsych, stage }: Ctx,
): Promise<TrialOutcome[]> {
  const end = performance.now() + item.seconds * 1000
  if (item.task === 'tapping') {
    const tap = button('Tap!', 'tap')
    const count = el('div', 'ml-word', '0')
    let taps = 0
    tap.addEventListener('pointerdown', () => {
      taps += 1
      count.textContent = String(taps)
    })
    stage.append(el('p', '', 'Tap as fast as you can until the time runs out.'), count, tap)
    await wait(item.seconds * 1000)
    return []
  }
  const sum = el('div', 'ml-word')
  const yes = button('F: true', 'sum-true')
  const no = button('J: false', 'sum-false')
  stage.append(el('p', '', 'Quick maths: is it true?'), sum, row(yes, no))
  for (const p of item.problems) {
    const left = end - performance.now()
    if (left <= 0) break
    sum.textContent = p.text
    await waitForResponse(jsPsych, {
      keys: ['f', 'j'],
      targets: [
        { element: yes, key: 'f' },
        { element: no, key: 'j' },
      ],
      deadlineMs: left,
    })
  }
  const rest = end - performance.now()
  if (rest > 0) await wait(rest)
  return []
}

async function recall(item: Of<'recall'>, { stage, e2e }: Ctx): Promise<TrialOutcome[]> {
  const answer: string[] = []
  const line = el('div', 'ml-word')
  const grid = el('div', 'oo-grid')
  grid.style.gridTemplateColumns = `repeat(${String(Math.min(5, item.palette.length))}, auto)`
  item.palette.forEach((x, i) => {
    const b = button(x, `pick-${String(i)}`, 'oo-item')
    b.addEventListener('click', () => {
      answer.push(x)
      line.textContent = answer.join(' ')
    })
    grid.append(b)
  })
  const clear = button('Clear', 'recall-clear')
  clear.addEventListener('click', () => {
    answer.length = 0
    line.textContent = ''
  })
  const done = button('Done', 'recall-done')
  const how = item.kind === 'ordered' ? 'in the order you saw them' : 'in any order'
  stage.append(el('p', '', `Tap what you saw, ${how}.`), line, grid, row(clear, done))
  const ids = item.target.map((t) => `pick-${String(item.palette.indexOf(t))}`)
  markAnswer(stage, e2e, `clicks:${[...ids, 'recall-done'].join('|')}`)
  const started = performance.now()
  await Promise.race([
    new Promise<void>((resolve) => {
      done.addEventListener('click', () => {
        resolve()
      })
    }),
    wait(config.recall_deadline_ms),
  ])
  const rt = performance.now() - started
  return scoreRecall(item.kind, item.target, answer).map((correct, i) => ({
    stimulus: { block: 'recall', kind: item.kind, item: item.target[i], position: i },
    response: { answer: [...answer] },
    correct,
    rt_ms: rt,
  }))
}

async function recognition(item: Of<'recognition'>, { jsPsych, stage, e2e }: Ctx) {
  const shown = el('div', 'ml-word')
  const isNew = button('F: new', 'probe-new')
  const seen = button('J: seen it', 'probe-seen')
  stage.append(el('p', '', 'Did you see this one?'), shown, row(isNew, seen))
  const out: TrialOutcome[] = []
  for (const probe of item.probes) {
    shown.textContent = probe.item
    const r = await waitForResponse(jsPsych, {
      keys: ['f', 'j'],
      targets: [
        { element: isNew, key: 'f' },
        { element: seen, key: 'j' },
      ],
      deadlineMs: config.recognition_deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, `key:${probe.seen ? 'j' : 'f'}`)
      },
    })
    out.push({
      stimulus: { block: 'recognition', item: probe.item, seen: probe.seen },
      response: r.key === null ? null : { key: r.key },
      correct: r.key !== null && (r.key === 'j') === probe.seen,
      rt_ms: r.rt,
    })
  }
  return out
}

async function choice(item: Of<'choice'>, { jsPsych, stage, e2e }: Ctx): Promise<TrialOutcome> {
  const keys = item.options.map((_, i) => String(i + 1))
  const buttons = item.options.map((o, i) =>
    button(`${String(i + 1)}: ${o}`, `option-${String(i)}`),
  )
  stage.append(el('p', 'ml-word', item.question), row(...buttons))
  const r = await waitForResponse(jsPsych, {
    keys,
    targets: buttons.map((element, i) => ({ element, key: String(i + 1) })),
    deadlineMs: config.choice_deadline_ms,
    onReady: () => {
      markAnswer(stage, e2e, `key:${String(item.options.indexOf(item.answer) + 1)}`)
    },
  })
  const picked = r.key === null ? null : (item.options[Number(r.key) - 1] ?? null)
  return {
    stimulus: { block: 'choice', question: item.question, options: item.options },
    response: picked === null ? null : { option: picked },
    correct: picked === item.answer,
    rt_ms: r.rt,
  }
}

async function timer(item: Of<'timer'>, { stage }: Ctx): Promise<TrialOutcome[]> {
  const count = el('div', 'ml-word')
  stage.append(count)
  for (let s = item.seconds; s > 0; s--) {
    count.textContent = String(s)
    await wait(1000)
  }
  return []
}

const RULE_TEXT = {
  odd_even: 'F if odd, J if even',
  high_low: 'F if below 5, J if above 5',
} as const

async function rule(item: Of<'rule'>, { jsPsych, stage, e2e }: Ctx): Promise<TrialOutcome[]> {
  const hint = el('p')
  const n = el('div', 'ml-word')
  const f = button('F', 'rule-f')
  const j = button('J', 'rule-j')
  stage.append(hint, n, row(f, j))
  const out: TrialOutcome[] = []
  let previous: string | null = null
  for (const trial of item.trials) {
    hint.textContent = RULE_TEXT[trial.rule]
    n.textContent = String(trial.n)
    const r = await waitForResponse(jsPsych, {
      keys: ['f', 'j'],
      targets: [
        { element: f, key: 'f' },
        { element: j, key: 'j' },
      ],
      deadlineMs: config.rule_deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, `key:${ruleKey(trial)}`)
      },
    })
    out.push({
      stimulus: { block: 'rule', ...trial, switched: previous !== null && previous !== trial.rule },
      response: r.key === null ? null : { key: r.key },
      correct: r.key === ruleKey(trial),
      rt_ms: r.rt,
    })
    previous = trial.rule
  }
  return out
}

async function react(item: Of<'react'>, { jsPsych, stage, e2e }: Ctx): Promise<TrialOutcome[]> {
  const shown = el('div', 'ml-word')
  const tap = button('Space or tap', 'react-tap')
  stage.append(shown, tap)
  const out: TrialOutcome[] = []
  for (const trial of item.trials) {
    shown.textContent = ''
    await wait(trial.isi_ms)
    shown.textContent = trial.stim
    const r = await waitForResponse(jsPsych, {
      keys: [' '],
      targets: [{ element: tap, key: ' ' }],
      deadlineMs: item.deadline_ms,
      onReady: () => {
        markAnswer(stage, e2e, trial.target ? 'key: ' : 'none')
      },
    })
    out.push({
      stimulus: {
        block: 'react',
        stim: trial.stim,
        target: trial.target,
        deadline_ms: item.deadline_ms,
      },
      response: r.key === null ? null : { key: r.key },
      correct: (r.key !== null) === trial.target,
      rt_ms: r.rt,
    })
  }
  return out
}

async function feedback(item: Of<'feedback'>, { jsPsych, stage }: Ctx): Promise<TrialOutcome[]> {
  const done = jsPsych.data
    .get()
    .values()
    .flatMap((d: Record<string, unknown>) => (d['lodestar'] as TrialRecord[] | undefined) ?? [])
    .filter((t) => t.correct !== null)
  const right = done.filter((t) => t.correct === true).length
  stage.append(el('div', 'ml-word', `${String(right)} of ${String(done.length)} right so far`))
  if (item.level === 'full' && done.length > 0)
    stage.append(el('p', '', right / done.length >= 0.8 ? 'Strong going.' : 'Keep at it.'))
  await wait(config.feedback_ms)
  return []
}

const BlocksPlugin = makePlugin<BlockItem>(
  'lodestar-custom-blocks',
  async ({ jsPsych, stage, item, e2e }) => {
    const ctx = { jsPsych, stage, e2e }
    stage.append(el('p', '', item.title))
    switch (item.block) {
      case 'show_items':
        return showItems(item, ctx)
      case 'distractor':
        return distractor(item, ctx)
      case 'recall':
        return recall(item, ctx)
      case 'recognition':
        return recognition(item, ctx)
      case 'choice':
        return choice(item, ctx)
      case 'timer':
        return timer(item, ctx)
      case 'rule':
        return rule(item, ctx)
      case 'react':
        return react(item, ctx)
      case 'feedback':
        return feedback(item, ctx)
    }
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice && t.correct !== null)
  const out: Record<string, number> = {
    accuracy: scored.length ? scored.filter((t) => t.correct).length / scored.length : 0,
  }
  const rt = median(
    scored.filter((t) => t.correct && t.rt_ms !== null).map((t) => t.rt_ms as number),
  )
  if (rt !== null) out['median_rt_ms'] = rt
  return out
}

export const game: GameModule = {
  id: 'custom_blocks',
  name: 'Custom Game',
  instructions:
    'Lodestar built this game from blocks for you. Each part tells you what to do. It counts only a little toward your profile for now.',
  keysHint: 'Follow the hint on each part: keys or taps.',
  timeline({ spec, rng, e2e }) {
    const recipe = spec.content as unknown as Recipe | null
    if (!recipe?.steps) throw new Error('This custom game has no recipe from the server.')
    return itemsToTimeline(BlocksPlugin, buildItems(recipe, rng), 0, e2e)
  },
  metrics,
}
