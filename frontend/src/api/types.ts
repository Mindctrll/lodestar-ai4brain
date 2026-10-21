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
export type Persona = 'zitouna' | 'barq' | 'hikma' | 'sahbi'
export type ProgressView = Schemas['ProgressView']
export type ForecastView = Schemas['ForecastView']
export type AcsView = Schemas['AcsView']
export type TraceRow = Schemas['TraceRow']
export type DimensionView = Schemas['DimensionView']
export type Dimension = Schemas['Dimension']
export type MeView = Schemas['MeView']

/** A write Najma wants to make, waiting for the user's yes (docs/plan/03, converse tools). */
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
  | { kind: 'session'; status: string; rounds: number }
  | {
      kind: 'interrupt'
      id: string
      payload: { type: 'exercise'; spec: ExerciseSpec } | ConfirmRequest
    }
  | { kind: 'done'; waiting: boolean }
