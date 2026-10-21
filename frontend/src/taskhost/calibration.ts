import type { TrialRecord } from './types'

/** Calibration of the "How sure are you?" answers (docs/plan/05, accuracy awareness): the gap
 * between mean confidence and accuracy, and the Brier score. */
export function calibration(records: TrialRecord[]): Record<string, number> {
  const probed = records.filter((r) => r.confidence !== undefined && r.correct !== null)
  if (probed.length === 0) return {}
  const hit = (r: TrialRecord) => (r.correct === true ? 1 : 0)
  const mean = (f: (r: TrialRecord) => number) =>
    probed.reduce((sum, r) => sum + f(r), 0) / probed.length
  return {
    probes: probed.length,
    calibration_error: Math.abs(mean((r) => r.confidence ?? 0) - mean(hit)),
    brier_score: mean((r) => ((r.confidence ?? 0) - hit(r)) ** 2),
  }
}
