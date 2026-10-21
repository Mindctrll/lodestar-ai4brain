import type { JsPsych } from 'jspsych'

import { median } from '../../lib/rng'
import { button, el, markAnswer } from '../../taskhost/plugin'
import { waitForResponse } from '../../taskhost/respond'
import type { TrialRecord } from '../../taskhost/types'
import { voiceAnswer } from '../../voice/answer'
import type { SpokenAnswer } from '../../voice/spokenAnswer'

export interface Chosen {
  index: number | null
  rt: number | null
}

/** A row of answer buttons (`choice-<i>`), each with an optional key. `answer` is the right
 * index for end-to-end tests, or null when the right move is to wait. */
export async function choose(
  jsPsych: JsPsych,
  stage: HTMLElement,
  e2e: boolean,
  labels: readonly string[],
  answer: number | null,
  options: { keys?: string[]; deadlineMs?: number | null; onReady?: () => void } = {},
): Promise<Chosen> {
  const row = el('div', 'choice-row')
  const buttons = labels.map((label, i) => button(label, `choice-${String(i)}`, 'choice'))
  row.append(...buttons)
  stage.append(row)
  const ids = options.keys ?? labels.map((_, i) => String(i))
  const response = await waitForResponse(jsPsych, {
    keys: options.keys ?? [],
    targets: buttons.map((element, i) => ({ element, key: ids[i] ?? String(i) })),
    deadlineMs: options.deadlineMs ?? null,
    onReady: () => {
      markAnswer(stage, e2e, answer === null ? 'none' : `click:choice-${String(answer)}`)
      options.onReady?.()
    },
  })
  return { index: response.key === null ? null : ids.indexOf(response.key), rt: response.rt }
}

/** A text box (`recall-input`) with a Done button (`recall-done`); Enter also submits when
 * `multiline` is off. With `say`, a "Say it" button adds a spoken answer to the box. Resolves with what was typed when Done is pressed or time runs out. */
export async function typeIn(
  jsPsych: JsPsych,
  stage: HTMLElement,
  e2e: boolean,
  expected: string,
  options: {
    label: string
    deadlineMs?: number | null
    multiline?: boolean
    numeric?: boolean
    say?: { pick: (answer: SpokenAnswer) => string; maxMs?: number }
  },
): Promise<{ text: string; rt: number | null; timedOut: boolean }> {
  const input = options.multiline ? el('textarea', 'ml-input') : el('input', 'type-input')
  input.dataset['testid'] = 'recall-input'
  input.setAttribute('aria-label', options.label)
  input.placeholder = options.label
  if (input instanceof HTMLInputElement && options.numeric) input.inputMode = 'numeric'
  const done = button('Done', 'recall-done')
  const say = options.say && voiceAnswer(input, 'Say it', options.say.pick, options.say.maxMs)
  const row = el('div', 'type-row')
  row.append(input, ...(say ? [say.button] : []), done)
  stage.append(row)
  input.focus()
  if (!options.multiline) {
    input.addEventListener('keydown', (event: Event) => {
      if ((event as KeyboardEvent).key === 'Enter')
        done.dispatchEvent(new PointerEvent('pointerdown'))
    })
  }
  const response = await waitForResponse(jsPsych, {
    keys: [],
    targets: [{ element: done, key: 'done' }],
    deadlineMs: options.deadlineMs ?? null,
    onReady: () => {
      markAnswer(stage, e2e, `type:${expected}`)
    },
  })
  say?.cancel()
  return { text: input.value.trim(), rt: response.rt, timedOut: response.key === null }
}

/** Listen for taps and keys until `onTap` returns true or time runs out. Unlike a chain of
 * waitForResponse calls, no tap is lost between two answers. Resolves with whether `onTap`
 * finished it. */
export function taps(
  targets: { element: HTMLElement; key: string }[],
  options: {
    keys?: string[]
    deadlineMs: number
    onTap: (key: string, msSinceStart: number) => boolean
    onReady?: () => void
  },
): Promise<boolean> {
  return new Promise((resolve) => {
    const started = performance.now()
    const cleanups: (() => void)[] = []
    const end = (finished: boolean) => {
      for (const cleanup of cleanups) cleanup()
      resolve(finished)
    }
    const handle = (key: string) => {
      if (options.onTap(key, performance.now() - started)) end(true)
    }
    for (const { element, key } of targets) {
      const listener = (event: PointerEvent) => {
        event.preventDefault()
        handle(key)
      }
      element.addEventListener('pointerdown', listener)
      cleanups.push(() => {
        element.removeEventListener('pointerdown', listener)
      })
    }
    if (options.keys?.length) {
      const listener = (event: KeyboardEvent) => {
        const k = event.key.toLowerCase()
        if (options.keys?.includes(k) && !event.repeat) handle(k)
      }
      document.addEventListener('keydown', listener)
      cleanups.push(() => {
        document.removeEventListener('keydown', listener)
      })
    }
    const timer = window.setTimeout(() => {
      end(false)
    }, options.deadlineMs)
    cleanups.push(() => {
      window.clearTimeout(timer)
    })
    options.onReady?.()
  })
}

/** A new answer inside the same step (each sum of Sum & Keep, each name of Name Tags): clears
 * the expected answer and gives end-to-end tests a fresh step id. */
export function nextAnswer(stage: HTMLElement, part: number): void {
  delete stage.dataset['answer']
  stage.dataset['trial'] = `${stage.dataset['trial']?.split('.')[0] ?? ''}.${String(part)}`
}

export const scored = (trials: TrialRecord[]) => trials.filter((t) => !t.practice)

export function accuracy(trials: TrialRecord[]): number {
  const s = scored(trials).filter((t) => t.correct !== null)
  return s.length ? s.filter((t) => t.correct === true).length / s.length : 0
}

/** Median response time of the scored, correct trials that pass `where`. */
export function medianRt(
  trials: TrialRecord[],
  where: (t: TrialRecord) => boolean = () => true,
): number | null {
  return median(
    scored(trials)
      .filter((t) => t.correct === true && t.rt_ms !== null && where(t))
      .map((t) => t.rt_ms as number),
  )
}

/** Right answers per minute of answering time. */
export function perMinute(trials: TrialRecord[]): number {
  const s = scored(trials)
  const ms = s.reduce((sum, t) => sum + (t.rt_ms ?? 0), 0)
  return ms > 0 ? (s.filter((t) => t.correct === true).length * 60_000) / ms : 0
}
