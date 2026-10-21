import { parse } from 'yaml'

import { median, randInt, shuffle, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { practiceFeedback } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, scored, taps } from '../shared/ask'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { trials: number; deadline_ms: number; dual_share: number }

type Rule = 'even' | 'odd'

export interface TowerItem {
  rule: Rule
  rule_changed: boolean
  planes: number[]
  /** Index of the one plane that follows the rule. */
  target: number
  /** On dual steps the radar also shows a colour to report. */
  dual: boolean
  radar: 'red' | 'green' | null
  deadline_ms: number
}

export function makeItems(rng: Rng, count: number, planes: number, changeRate: number) {
  let rule: Rule = 'even'
  return Array.from({ length: count }, (_, i): TowerItem => {
    const changed = i > 0 && rng() < changeRate
    if (changed) rule = rule === 'even' ? 'odd' : 'even'
    const parity = rule === 'even' ? 0 : 1
    const right = 2 * randInt(rng, 1, 49) + parity
    const others = Array.from({ length: planes - 1 }, () => 2 * randInt(rng, 1, 49) + 1 - parity)
    const numbers = shuffle(rng, [right, ...others])
    const dual = rng() < config.dual_share
    return {
      rule,
      rule_changed: changed,
      planes: numbers,
      target: numbers.indexOf(right),
      dual,
      radar: dual ? (rng() < 0.5 ? 'red' : 'green') : null,
      deadline_ms: config.deadline_ms,
    }
  })
}

/** Wait for an answer to every job on screen; each answer is (choice, ms from the start). */
async function answers(
  jobs: Record<string, HTMLButtonElement[]>,
  deadlineMs: number,
  onReady: () => void,
): Promise<Record<string, { choice: number; rt: number }>> {
  const got: Record<string, { choice: number; rt: number }> = {}
  await taps(
    Object.entries(jobs).flatMap(([job, buttons]) =>
      buttons.map((element, i) => ({ element, key: `${job}:${String(i)}` })),
    ),
    {
      deadlineMs,
      onReady,
      onTap: (key, ms) => {
        const [job = '', choice = '0'] = key.split(':')
        if (job in got) return false
        got[job] = { choice: Number(choice), rt: ms }
        for (const b of jobs[job] ?? []) b.disabled = true
        return Object.keys(got).length === Object.keys(jobs).length
      },
    },
  )
  return got
}

const TowerPlugin = makePlugin<TowerItem>(
  'najma-control-tower',
  async ({ stage, item, practice, e2e }) => {
    const rule = el('p', `ct-rule${item.rule_changed ? ' is-new' : ''}`)
    rule.textContent = `${item.rule_changed ? 'New rule: ' : ''}land the ${item.rule.toUpperCase()} plane`
    const field = el('div', 'ct-planes')
    const planes = item.planes.map((n, i) =>
      button(`✈ ${String(n)}`, `plane-${String(i)}`, 'ct-plane'),
    )
    field.append(...planes)
    stage.append(rule, field)
    const jobs: Record<string, HTMLButtonElement[]> = { land: planes }
    if (item.dual && item.radar) {
      const radar = el('div', `ct-radar is-${item.radar}`)
      radar.setAttribute('aria-label', `Radar light: ${item.radar}`)
      const report = [button('Red alert', 'radar-0'), button('All clear', 'radar-1')]
      const row = el('div', 'choice-row')
      row.append(...report)
      stage.append(radar, row)
      jobs['radar'] = report
    }
    const radarRight = item.radar === 'red' ? 0 : 1
    const got = await answers(jobs, item.deadline_ms, () => {
      const clicks = [`plane-${String(item.target)}`]
      if (item.dual) clicks.push(`radar-${String(radarRight)}`)
      markAnswer(stage, e2e, `clicks:${clicks.join('|')}`)
    })
    const land = got['land']
    const radar = got['radar']
    const landed = land?.choice === item.target
    const reported = radar?.choice === radarRight
    if (practice) await practiceFeedback(stage, landed && (!item.dual || reported))
    const stimulus = { rule: item.rule, rule_changed: item.rule_changed, dual: item.dual }
    const out = [
      {
        stimulus: { ...stimulus, job: 'land', planes: item.planes, deadline_ms: item.deadline_ms },
        response: land ? { plane: land.choice } : null,
        correct: landed,
        rt_ms: land?.rt ?? null,
      },
    ]
    if (item.dual)
      out.push({
        stimulus: { ...stimulus, job: 'radar', planes: [], deadline_ms: item.deadline_ms },
        response: radar ? { plane: radar.choice } : null,
        correct: reported,
        rt_ms: radar?.rt ?? null,
      })
    return out
  },
)

/** Dual-task cost: how much slower landing gets when the radar needs watching too. */
export function metrics(trials: TrialRecord[]): Record<string, number> {
  const out: Record<string, number> = { accuracy: accuracy(trials) }
  const landing = scored(trials).filter((t) => t.stimulus['job'] === 'land' && t.correct === true)
  const rt = (dual: boolean) =>
    median(landing.filter((t) => t.stimulus['dual'] === dual).map((t) => t.rt_ms ?? 0))
  const single = rt(false)
  const both = rt(true)
  if (single !== null && both !== null && single > 0)
    out['dual_task_cost'] = (both - single) / single
  return out
}

export const game: GameModule = {
  id: 'control_tower',
  name: 'Control Tower',
  instructions:
    'Land the plane whose number follows the rule (even or odd). The rule can change. When the radar lights up, also report its colour.',
  keysHint: 'Tap or click the plane, then the radar report when there is one.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      Math.max(2, Math.round(spec.knobs['planes'] ?? 3)),
      spec.knobs['rule_change_rate'] ?? 0.1,
    )
    return itemsToTimeline(TowerPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
