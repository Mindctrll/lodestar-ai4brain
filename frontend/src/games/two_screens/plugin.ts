import { parse } from 'yaml'

import { median, randInt, shuffle, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, choose, scored } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as {
  questions: number
  deadline_ms: number
  lead_max_ms: number
  band: number
  nudge: number
}

export interface Question {
  text: string
  /** 0 is Yes, 1 is No. */
  answer: number
}

export interface ScreensItem {
  /** Dual steps: the dot drifts and must be kept in the middle while the question is answered. */
  dual: boolean
  question: Question
  lead_ms: number
  speed: number
}

export function question(rng: Rng): Question {
  const n = randInt(rng, 2, 98)
  if (rng() < 0.5) return { text: `Is ${String(n)} an even number?`, answer: n % 2 === 0 ? 0 : 1 }
  const m = randInt(rng, 10, 90)
  return { text: `Is ${String(n)} more than ${String(m)}?`, answer: n > m ? 0 : 1 }
}

/** Half the steps are the question alone, half with the dot to track (dual-task paradigm,
 * Pashler, 1994). `rate` is questions per second while tracking, so a higher rate means less
 * tracking time before each question. */
export function makeItems(rng: Rng, count: number, speed: number, rate: number): ScreensItem[] {
  const lead = Math.min(config.lead_max_ms, 1000 / Math.max(0.05, rate))
  const kinds = shuffle(
    rng,
    Array.from({ length: count }, (_, i) => i % 2 === 1),
  )
  return kinds.map((dual) => ({ dual, question: question(rng), lead_ms: dual ? lead : 500, speed }))
}

/** The dot drifts on its own and turns at random; the arrows nudge it back. */
function track(stage: HTMLElement, speed: number): () => number {
  const box = el('div', 'ts-track')
  const band = el('div', 'ts-band')
  band.style.width = `${String(config.band * 100)}%`
  const dot = el('div', 'ts-dot')
  box.append(band, dot)
  const left = button('◀', 'track-left')
  const right = button('▶', 'track-right')
  left.setAttribute('aria-label', 'Move the dot left')
  right.setAttribute('aria-label', 'Move the dot right')
  const row = el('div', 'choice-row')
  row.append(left, right)
  stage.append(box, row)
  let pos = 0
  let dir = Math.random() < 0.5 ? -1 : 1
  let ticks = 0
  let inside = 0
  const nudge = (d: number) => {
    pos = Math.max(-1, Math.min(1, pos + d * config.nudge))
  }
  const onLeft = (e: Event) => {
    e.preventDefault()
    nudge(-1)
  }
  const onRight = (e: Event) => {
    e.preventDefault()
    nudge(1)
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') nudge(-1)
    if (e.key === 'ArrowRight') nudge(1)
  }
  left.addEventListener('pointerdown', onLeft)
  right.addEventListener('pointerdown', onRight)
  document.addEventListener('keydown', onKey)
  const timer = window.setInterval(() => {
    if (Math.random() < 0.04) dir = -dir
    pos = Math.max(-1, Math.min(1, pos + dir * speed * 0.02))
    if (Math.abs(pos) === 1) dir = -dir
    ticks += 1
    if (Math.abs(pos) <= config.band) inside += 1
    dot.style.left = `${String((pos + 1) * 50)}%`
  }, 50)
  return () => {
    window.clearInterval(timer)
    document.removeEventListener('keydown', onKey)
    left.removeEventListener('pointerdown', onLeft)
    right.removeEventListener('pointerdown', onRight)
    return ticks ? inside / ticks : 0
  }
}

const ScreensPlugin = makePlugin<ScreensItem>(
  'najma-two-screens',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const stop = item.dual ? track(stage, item.speed) : null
    await wait(item.lead_ms)
    stage.append(el('p', 'game-prompt', item.question.text))
    const { index, rt } = await choose(
      jsPsych,
      stage,
      e2e,
      ['Yes (Y)', 'No (N)'],
      item.question.answer,
      { keys: ['y', 'n'], deadlineMs: config.deadline_ms },
    )
    const onTarget = stop ? stop() : null
    const correct = index === item.question.answer
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { dual: item.dual, question: item.question.text, speed: item.speed },
      response: index === null ? null : { answer: index, on_target: onTarget },
      correct,
      rt_ms: rt,
    }
  },
)

/** Dual-task cost: how much slower the questions are while tracking (median, right answers). */
export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials).filter((t) => t.correct === true && t.rt_ms !== null)
  const rt = (dual: boolean) =>
    median(s.filter((t) => t.stimulus['dual'] === dual).map((t) => t.rt_ms as number))
  const single = rt(false)
  const dual = rt(true)
  const tracked = scored(trials)
    .filter((t) => t.stimulus['dual'] === true && t.response !== null)
    .map((t) => Number(t.response?.['on_target'] ?? 0))
  const out: Record<string, number> = {
    accuracy: accuracy(trials),
  }
  if (single !== null && dual !== null) out['dual_task_cost'] = dual - single
  if (tracked.length) out['on_target'] = tracked.reduce((a, b) => a + b, 0) / tracked.length
  return out
}

export const game: GameModule = {
  id: 'two_screens',
  name: 'Two Screens',
  instructions:
    'Answer the yes-or-no questions. On some steps a dot drifts along a bar: keep it in the middle with the arrows while you answer.',
  keysHint: 'Y or N to answer, ← and → to move the dot, or tap the buttons.',
  timeline({ spec, rng, e2e }) {
    const speed = spec.knobs['dot_speed'] ?? 1
    const rate = spec.knobs['question_rate'] ?? 0.25
    const practice = Math.min(2, spec.practice_trials)
    const items = [
      ...makeItems(rng, practice, speed, rate).sort((a, b) => Number(a.dual) - Number(b.dual)),
      ...makeItems(rng, config.questions, speed, rate),
    ]
    return itemsToTimeline(ScreensPlugin, items, practice, e2e)
  },
  metrics,
}
