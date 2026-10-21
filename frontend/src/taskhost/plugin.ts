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

const PARAMETERS = {
  item: { type: ParameterType.OBJECT, default: {} },
  trial_index: { type: ParameterType.INT, default: 0 },
  practice: { type: ParameterType.BOOL, default: false },
  e2e: { type: ParameterType.BOOL, default: false },
}

/** Build a jsPsych plugin whose trials are described by one precomputed `item`. Every game's
 * plugin is made this way, so they all record the same fields (docs/plan/06). */
export function makePlugin<I>(
  name: string,
  run: (ctx: TrialContext<I>) => Promise<TrialOutcome>,
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
      display.innerHTML = `<div class="najma-stage" data-testid="stage" data-trial="${index}"></div>`
      const stage = display.querySelector<HTMLElement>('.najma-stage')
      if (!stage) throw new Error('stage missing')
      const practice = trial['practice'] === true
      const outcome = await run({
        jsPsych: this.jsPsych,
        stage,
        item: trial['item'] as I,
        practice,
        e2e: trial['e2e'] === true,
      })
      display.innerHTML = ''
      this.jsPsych.finishTrial({
        najma: { ...outcome, trial_index: trial['trial_index'] as number, practice },
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
  }))
}
