import { parse } from 'yaml'

import { pick, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, choose, medianRt } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { trials: number; deadline_ms: number; fixation_ms: number }

type Side = 'left' | 'right'

export interface CueItem {
  cue: Side
  target: Side
  valid: boolean
  soa_ms: number
  deadline_ms: number
}

export function makeItems(rng: Rng, count: number, validity: number, soa: number): CueItem[] {
  return Array.from({ length: count }, () => {
    const cue = pick(rng, ['left', 'right'] as const)
    const valid = rng() < validity
    const target: Side = valid ? cue : cue === 'left' ? 'right' : 'left'
    return { cue, target, valid, soa_ms: soa, deadline_ms: config.deadline_ms }
  })
}

const CuePlugin = makePlugin<CueItem>(
  'lodestar-look-here',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const field = el('div', 'lh-field')
    const boxes = { left: el('div', 'lh-box'), right: el('div', 'lh-box') }
    const centre = el('div', 'lh-centre', '+')
    field.append(boxes.left, centre, boxes.right)
    stage.append(field)
    await wait(config.fixation_ms)
    centre.textContent = item.cue === 'left' ? '←' : '→'
    await wait(item.soa_ms)
    boxes[item.target].textContent = '●'
    boxes[item.target].dataset['testid'] = 'lh-target'
    const { index, rt } = await choose(
      jsPsych,
      stage,
      e2e,
      ['Left', 'Right'],
      item.target === 'left' ? 0 : 1,
      { keys: ['arrowleft', 'arrowright'], deadlineMs: item.deadline_ms },
    )
    const correct = index === (item.target === 'left' ? 0 : 1)
    if (practice) await practiceFeedback(stage, correct)
    return {
      stimulus: { ...item },
      response: index === null ? null : { side: index === 0 ? 'left' : 'right' },
      correct,
      rt_ms: rt,
    }
  },
)

/** The cueing effect (Posner, 1980): slower answers when the hint pointed the wrong way. */
export function metrics(trials: TrialRecord[]): Record<string, number> {
  const out: Record<string, number> = { accuracy: accuracy(trials) }
  const valid = medianRt(trials, (t) => t.stimulus['valid'] === true)
  const invalid = medianRt(trials, (t) => t.stimulus['valid'] === false)
  if (valid !== null && invalid !== null) out['cue_validity_effect_ms'] = invalid - valid
  return out
}

export const game: GameModule = {
  id: 'look_here',
  name: 'Look Here',
  instructions:
    'An arrow hints where a dot will appear. Usually it’s right, sometimes not. Press the side where the dot shows up.',
  keysHint: 'Left and Right arrow keys, or tap the buttons.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['cue_validity'] ?? 0.8,
      spec.knobs['soa_ms'] ?? 200,
    )
    return itemsToTimeline(CuePlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
