import { ParameterType, type JsPsych, type JsPsychPlugin, type PluginInfo } from 'jspsych'

import type { TrialRecord } from './types'

export interface TrialContext<I> {
  jsPsych: JsPsych
  stage: HTMLElement
  item: I
  practice: boolean
  e2e: boolean
}

export type TrialOutcome = Omit<TrialRecord, 'trial_index' | 'practice'>

/** Some steps score several things at once (each word of a recalled list, each customer's
 * basket); they return one outcome per scored item. */
export type StepOutcome = TrialOutcome | TrialOutcome[]

/** Expected answer for end-to-end tests, as one action Playwright can perform:
 * `key:<key>`, `click:<testid>`, `clicks:<a>|<b>`, `type:<words>`, `point:<testid>:<0..1>`, `none`;
 * several in order are joined with ` >> `. */
export function markAnswer(stage: HTMLElement, e2e: boolean, answer: string): void {
  if (e2e) stage.dataset['answer'] = answer
}

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text !== undefined) node.textContent = text
  return node
}

export function button(label: string, testid: string, className = ''): HTMLButtonElement {
  const b = el('button', className, label)
  b.type = 'button'
  b.dataset['testid'] = testid
  return b
}

const PARAMETERS = {
  item: { type: ParameterType.OBJECT, default: {} },
  trial_index: { type: ParameterType.INT, default: 0 },
  practice: { type: ParameterType.BOOL, default: false },
  e2e: { type: ParameterType.BOOL, default: false },
  probe: { type: ParameterType.BOOL, default: false },
}

/** "How sure are you?" (docs/plan/06): after about one answer in ten, in any game, a confidence
 * slider. Practice answers and unanswered steps are never probed. */
export const PROBE_EVERY = 10

export const isProbed = (index: number, practice: number) =>
  index >= practice && (index * 7) % PROBE_EVERY === 3

async function howSure(stage: HTMLElement, e2e: boolean, index: string): Promise<number> {
  stage.replaceChildren()
  stage.dataset['trial'] = `${index}.sure`
  const box = el('div', 'how-sure')
  const label = el('label', '', 'How sure are you that you got that one right?')
  const slider = el('input')
  slider.type = 'range'
  slider.min = '50'
  slider.max = '100'
  slider.step = '5'
  slider.value = '75'
  slider.dataset['testid'] = 'sure-slider'
  slider.setAttribute('aria-label', 'How sure, from a guess (50%) to certain (100%)')
  const shown = el('span', '', '75%')
  slider.addEventListener('input', () => {
    shown.textContent = `${slider.value}%`
  })
  label.append(slider)
  const done = button('OK', 'sure-done')
  box.append(label, shown, done)
  stage.append(box)
  markAnswer(stage, e2e, 'click:sure-done')
  await new Promise<void>((resolve) => {
    done.addEventListener('pointerdown', () => {
      resolve()
    })
  })
  return Number(slider.value) / 100
}

/** Build a jsPsych plugin whose trials are described by one precomputed `item`. Every game's
 * plugin is made this way, so they all record the same fields (docs/plan/06). */
export function makePlugin<I>(
  name: string,
  run: (ctx: TrialContext<I>) => Promise<StepOutcome>,
): new (jsPsych: JsPsych) => JsPsychPlugin<PluginInfo> {
  class NajmaPlugin implements JsPsychPlugin<PluginInfo> {
    static info: PluginInfo = {
      name,
      version: '1.0.0',
      parameters: PARAMETERS,
      data: { najma: { type: ParameterType.OBJECT } },
    }

    constructor(private readonly jsPsych: JsPsych) {}

    async trial(display: HTMLElement, trial: Record<string, unknown>): Promise<void> {
      const index = String(trial['trial_index'])
      const practice = trial['practice'] === true
      display.innerHTML = `<div class="najma-stage" data-testid="stage" data-trial="${index}" data-practice="${String(practice)}"></div>`
      const stage = display.querySelector<HTMLElement>('.najma-stage')
      if (!stage) throw new Error('stage missing')
      const outcome = await run({
        jsPsych: this.jsPsych,
        stage,
        item: trial['item'] as I,
        practice,
        e2e: trial['e2e'] === true,
      })
      if (
        trial['probe'] === true &&
        !practice &&
        !Array.isArray(outcome) &&
        outcome.correct !== null &&
        outcome.response !== null
      ) {
        outcome.confidence = await howSure(stage, trial['e2e'] === true, index)
      }
      display.innerHTML = ''
      const outcomes = Array.isArray(outcome) ? outcome : [outcome]
      const base = trial['trial_index'] as number
      this.jsPsych.finishTrial({
        najma: outcomes.map((o, i) => ({
          ...o,
          trial_index: base * 100 + i,
          practice,
        })),
      })
    }
  }
  return NajmaPlugin
}

/** Timeline entries for a list of items: the first `practice` ones get feedback. */
export function itemsToTimeline(
  plugin: new (jsPsych: JsPsych) => JsPsychPlugin<PluginInfo>,
  items: readonly unknown[],
  practice: number,
  e2e: boolean,
): Record<string, unknown>[] {
  return items.map((item, index) => ({
    type: plugin,
    item,
    trial_index: index,
    practice: index < practice,
    e2e,
    probe: isProbed(index, practice),
  }))
}
