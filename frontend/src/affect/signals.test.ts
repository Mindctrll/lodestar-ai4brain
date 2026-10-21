import type { TrialRecord } from '../taskhost/types'
import { currentMissStreak, longestMissStreak, summarise } from './signals'

const trial = (correct: boolean | null, rt = 500, practice = false, hint = 0): TrialRecord => ({
  trial_index: 0,
  practice,
  stimulus: {},
  response: null,
  correct,
  rt_ms: rt,
  hint_level: hint,
})

test('miss streaks skip practice and unscored trials', () => {
  const records = [
    trial(false, 500, true),
    trial(false),
    trial(false),
    trial(null),
    trial(false),
    trial(true),
    trial(false),
  ]
  expect(longestMissStreak(records)).toBe(3)
  expect(currentMissStreak(records)).toBe(1)
  expect(currentMissStreak([trial(true), trial(false), trial(false)])).toBe(2)
})

test('summarise reports how the round was played, never a score', () => {
  const records = [trial(true, 400), trial(false, 900, false, 2), trial(false, 450)]
  const s = summarise('test_game_a', records, 3, 'eased')
  expect(s.error_streak).toBe(2)
  expect(s.rapid_taps).toBe(3)
  expect(s.hint_burst).toBe(true)
  expect(s.too_hard_pressed).toBe(true)
  expect(s.quit_mid_game).toBe(false)
  expect(s.mood).toBeNull()
  expect(s.rt_variability_z).not.toBeNull()
})

test('RT is compared with the same user’s earlier rounds of the same game', () => {
  const first = summarise('test_game_b', [trial(true, 500), trial(true, 500)], 0, 'completed')
  expect(first.rt_z).toBeNull() // no baseline yet
  const slower = summarise('test_game_b', [trial(true, 800), trial(true, 800)], 0, 'completed')
  expect(slower.rt_z).toBeGreaterThan(1.5)
})
