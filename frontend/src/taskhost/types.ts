import type { ExerciseSpec } from '../api/types'
import type { Rng } from '../lib/rng'

/** Right answers out of the scored, judged steps of a round; shown to the player, not sent. */
export interface Score {
  right: number
  total: number
}

/** What every game records per trial (docs/plan/06, shared game rules). */
export interface TrialRecord {
  trial_index: number
  practice: boolean
  stimulus: Record<string, unknown>
  response: Record<string, unknown> | null
  correct: boolean | null
  rt_ms: number | null
  /** How many hints were shown before answering (the ACS autonomy signal). */
  hint_level?: number
  /** From the "How sure are you?" slider, 0.5 to 1, when this answer was probed. */
  confidence?: number
}

export interface GameContext {
  spec: ExerciseSpec
  rng: Rng
  /** Set by end-to-end tests: stimuli expose their expected answer in a data attribute. */
  e2e: boolean
}

export type TimelineItem = Record<string, unknown>

export interface GameModule {
  id: string
  name: string
  instructions: string
  keysHint: string
  timeline(ctx: GameContext): TimelineItem[]
  metrics(trials: TrialRecord[]): Record<string, number>
}

declare global {
  interface Window {
    __LODESTAR_E2E__?: boolean
  }
}
