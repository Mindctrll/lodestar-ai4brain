import type { components } from '../contracts/api'

type Schemas = components['schemas']

export type ExerciseSpec = Schemas['ExerciseSpec']
export type RoundResult = Schemas['RoundResult']
export type TrialEvent = Schemas['TrialEvent']
export type TwinView = Schemas['TwinView']
export type Registry = Schemas['Registry']
export type Game = Schemas['Game']
export type Decision = Schemas['Decision']
export type GoalView = Schemas['GoalView']
export type FactsPacket = Schemas['FactsPacket']
export type ConsentView = Schemas['ConsentView']
export type LlmOverview = Schemas['LlmOverview']
export type LlmSelection = Schemas['LlmSelection']
export type KeySaved = Schemas['KeySaved']
export type MyData = Schemas['MyData']
export type Receipt = Schemas['Receipt']
export type Persona = 'willow' | 'spark' | 'sage' | 'buddy'
export type ProgressView = Schemas['ProgressView']
export type ForecastView = Schemas['ForecastView']
export type AcsView = Schemas['AcsView']
export type TraceRow = Schemas['TraceRow']
export type DimensionView = Schemas['DimensionView']
export type Dimension = Schemas['Dimension']
export type MeView = Schemas['MeView']
export type ExperimentView = Schemas['ExperimentView']
export type InsightsView = Schemas['InsightsView']
export type ModelCard = Schemas['ModelCard']
export type PatternsView = Schemas['PatternsView']
export type PlateauView = Schemas['PlateauView']
export type SplitView = Schemas['SplitView']
export type WhyLine = Schemas['WhyLine']

/** A range that got wider: the estimate stays, the range says how sure Lodestar is. */
export interface WidenedRange {
  name: string
  value: number
  before_low: number
  before_high: number
  after_low: number
  after_high: number
}

/** A card the agent adds to the conversation, one kind per stress case. */
export type AgentCard =
  | {
      card: 'rushed'
      round_id: string
      game: string
      verdict: string
      median_rt_ms: number | null
      correct: number
      answered: number
      dims: WidenedRange[]
    }
  | {
      card: 'why'
      decision_id: string
      reason: string
      when: string
      lines: WhyLine[]
      chosen: string
    }
  | {
      card: 'history'
      rows: { day: string; game: string; score: number | null; decision_id: string | null }[]
    }
  | {
      card: 'forecast'
      sessions: number
      held: number | null
      rows: {
        name: string
        now: number
        now_low: number
        now_high: number
        low: number
        median: number
        high: number
      }[]
    }
  | {
      card: 'pushback'
      game: string
      dims: WidenedRange[]
      acs_before: number | null
      acs_after: number | null
      acs_low: number | null
      acs_high: number | null
    }

/** A write Lodestar wants to make, waiting for the user's yes (docs/plan/03, converse tools). */
export interface ConfirmRequest {
  type: 'confirm'
  call_id: string
  tool: string
  prompt: string
  facts: FactsPacket
}

/** One event streamed by the agent (docs/plan/03, "Streaming and the agent timeline"). */
export type AgentEvent =
  | { kind: 'node'; node: string; status: 'start' | 'done' | 'error'; ms?: number }
  | { kind: 'decision'; node: string; decision_id: string; chosen: string; reason: string }
  | { kind: 'degraded'; what: string; from: string; to: string; node: string }
  | {
      kind: 'say'
      text: string
      node?: string
      template?: string
      /** Citation id -> decision id, for the "why" card behind [D1]. */
      refs?: Record<string, string> | undefined
    }
  | { kind: 'memory'; text: string }
  | ({ kind: 'card' } & AgentCard)
  /** What route_intent understood; the UI opens the matching surface beside the reply. */
  | { kind: 'intent'; intent: string; dim: string | null; tool: string | null }
  | { kind: 'session'; status: string; rounds: number }
  | {
      kind: 'interrupt'
      id: string
      payload: { type: 'exercise'; spec: ExerciseSpec } | ConfirmRequest
    }
  | { kind: 'done'; waiting: boolean }
