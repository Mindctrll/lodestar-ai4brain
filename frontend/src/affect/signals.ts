import { median } from '../lib/rng'
import type { TrialRecord } from '../taskhost/types'

/** Behaviour signals for one round (docs/plan/12, "the main path"). No camera, no microphone:
 * only how the round was played. Summarised in the browser and sent with the round result. */
export interface BehaviourSignals {
  error_streak: number
  rt_z: number | null
  rt_variability_z: number | null
  rapid_taps: number
  hint_burst: boolean
  quit_mid_game: boolean
  too_hard_pressed: boolean
  mood: null
}

const BASELINE_KEY = (game: string) => `lodestar.baseline.${game}`
export const STRUGGLE_STREAK = 4

export function longestMissStreak(records: TrialRecord[]): number {
  let run = 0
  let best = 0
  for (const r of records) {
    if (r.practice || r.correct === null) continue
    run = r.correct ? 0 : run + 1
    best = Math.max(best, run)
  }
  return best
}

export function currentMissStreak(records: TrialRecord[]): number {
  let run = 0
  for (const r of [...records].reverse()) {
    if (r.practice || r.correct === null) continue
    if (r.correct) break
    run += 1
  }
  return run
}

function readBaseline(game: string): number | null {
  try {
    const raw = localStorage.getItem(BASELINE_KEY(game))
    return raw ? Number(raw) : null
  } catch {
    return null
  }
}

function writeBaseline(game: string, value: number): void {
  try {
    localStorage.setItem(BASELINE_KEY(game), String(value))
  } catch {
    // private mode: no baseline across rounds
  }
}

/** RT against this user's own previous rounds of the same game, never against other people. */
export function summarise(
  game: string,
  records: TrialRecord[],
  rapidTaps: number,
  status: 'completed' | 'stopped' | 'eased',
): BehaviourSignals {
  const rts = records.filter((r) => !r.practice && r.rt_ms !== null).map((r) => r.rt_ms as number)
  const med = median(rts)
  const baseline = readBaseline(game)
  let rtZ: number | null = null
  let variabilityZ: number | null = null
  if (med !== null) {
    if (baseline) rtZ = (med - baseline) / (0.25 * baseline)
    const mean = rts.reduce((a, b) => a + b, 0) / rts.length
    const sd = Math.sqrt(rts.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, rts.length - 1))
    variabilityZ = mean > 0 ? (sd / mean - 0.3) / 0.1 : null
    if (status === 'completed') writeBaseline(game, baseline ? 0.8 * baseline + 0.2 * med : med)
  }
  return {
    error_streak: longestMissStreak(records),
    rt_z: rtZ,
    rt_variability_z: variabilityZ,
    rapid_taps: rapidTaps,
    hint_burst: records.some((r) => (r.hint_level ?? 0) >= 2),
    quit_mid_game: status === 'stopped',
    too_hard_pressed: status === 'eased',
    mood: null,
  }
}
