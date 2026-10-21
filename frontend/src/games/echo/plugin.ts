import { parse } from 'yaml'

import { pick, type Rng } from '../../lib/rng'
import { itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, wait, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

interface Config {
  items_after_warmup: number
  target_rate: number
  show_ms: number
  match_key: string
  letters: string[]
}
const config = parse(rawConfig) as Config

export interface EchoItem {
  letter: string
  is_target: boolean
  n: number
  pace_ms: number
  warmup: boolean
}

export function makeItems(rng: Rng, n: number, paceMs: number, afterWarmup: number): EchoItem[] {
  const letters: string[] = []
  const items: EchoItem[] = []
  for (let i = 0; i < n + afterWarmup; i++) {
    const back = i >= n ? letters[i - n] : undefined
    const target = back !== undefined && rng() < config.target_rate
    const letter =
      target && back
        ? back
        : pick(
            rng,
            config.letters.filter((l) => l !== back),
          )
    letters.push(letter)
    items.push({ letter, is_target: target, n, pace_ms: paceMs, warmup: i < n })
  }
  return items
}

const EchoPlugin = makePlugin<EchoItem>(
  'najma-echo',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const letter = document.createElement('div')
    letter.className = 'echo-letter'
    letter.textContent = item.letter
    letter.dataset['testid'] = 'echo-letter'
    const match = document.createElement('button')
    match.type = 'button'
    match.className = 'echo-match'
    match.textContent = 'Match (Space)'
    match.dataset['testid'] = 'echo-match'
    stage.append(letter, match)
    const started = performance.now()
    const hide = window.setTimeout(
      () => {
        letter.textContent = ''
      },
      Math.min(config.show_ms, item.pace_ms),
    )
    const response = await waitForResponse(jsPsych, {
      keys: [config.match_key],
      targets: [{ element: match, key: config.match_key }],
      deadlineMs: item.pace_ms,
      onReady: () => {
        if (e2e) stage.dataset['answer'] = item.is_target ? 'match' : 'none'
      },
    })
    const pressed = response.key !== null
    const correct = pressed === item.is_target
    if (practice && !item.warmup) await practiceFeedback(stage, correct)
    // Keep the pace fixed whether or not the user answered early.
    await wait(Math.max(0, item.pace_ms - (performance.now() - started)))
    window.clearTimeout(hide)
    return {
      stimulus: { letter: item.letter, is_target: item.is_target, n: item.n, warmup: item.warmup },
      response: pressed ? { key: 'match' } : null,
      correct,
      rt_ms: response.rt,
    }
  },
)

/** d-prime with the log-linear correction (Hautus, 1995). */
export function dPrime(
  hits: number,
  misses: number,
  falseAlarms: number,
  correctRejections: number,
): number {
  const hitRate = (hits + 0.5) / (hits + misses + 1)
  const faRate = (falseAlarms + 0.5) / (falseAlarms + correctRejections + 1)
  return probit(hitRate) - probit(faRate)
}

function probit(p: number): number {
  // Acklam's rational approximation of the inverse normal CDF.
  const a = [
    -39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472,
    2.50662827745924,
  ]
  const b = [
    -54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857,
  ]
  const c = [
    -0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373,
    4.37466414146497, 2.93816398269878,
  ]
  const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742]
  const at = (arr: number[], i: number) => arr[i] ?? 0
  const low = 0.02425
  if (p < low) {
    const q = Math.sqrt(-2 * Math.log(p))
    return (
      (((((at(c, 0) * q + at(c, 1)) * q + at(c, 2)) * q + at(c, 3)) * q + at(c, 4)) * q +
        at(c, 5)) /
      ((((at(d, 0) * q + at(d, 1)) * q + at(d, 2)) * q + at(d, 3)) * q + 1)
    )
  }
  if (p > 1 - low) return -probit(1 - p)
  const q = p - 0.5
  const r = q * q
  return (
    ((((((at(a, 0) * r + at(a, 1)) * r + at(a, 2)) * r + at(a, 3)) * r + at(a, 4)) * r + at(a, 5)) *
      q) /
    (((((at(b, 0) * r + at(b, 1)) * r + at(b, 2)) * r + at(b, 3)) * r + at(b, 4)) * r + 1)
  )
}

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  const targets = scored.filter((t) => t.stimulus['is_target'] === true)
  const lures = scored.filter((t) => t.stimulus['is_target'] !== true)
  const hits = targets.filter((t) => t.correct === true).length
  const falseAlarms = lures.filter((t) => t.correct === false).length
  return {
    hits,
    false_alarms: falseAlarms,
    d_prime: dPrime(hits, targets.length - hits, falseAlarms, lures.length - falseAlarms),
    accuracy: scored.length ? scored.filter((t) => t.correct === true).length / scored.length : 0,
  }
}

export const game: GameModule = {
  id: 'echo',
  name: 'Echo',
  instructions:
    'Letters appear one at a time. Press Match when the letter is the same as the one n steps back. Otherwise, do nothing.',
  keysHint: 'Space, or tap Match.',
  timeline({ spec, rng, e2e }) {
    const n = Math.max(1, Math.min(4, Math.round(spec.knobs['n'] ?? 1)))
    const items = makeItems(rng, n, spec.knobs['pace_ms'] ?? 2500, config.items_after_warmup)
    // The first n letters can't be targets: they're shown, marked practice, and not scored.
    const practice = Math.max(spec.practice_trials, n)
    return itemsToTimeline(EchoPlugin, items, practice, e2e)
  },
  metrics,
}
