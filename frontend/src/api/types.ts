import type { components } from '../contracts/api'

type Schemas = components['schemas']

export type ExerciseSpec = Schemas['ExerciseSpec']
export type RoundResult = Schemas['RoundResult']
export type TrialEvent = Schemas['TrialEvent']
export type TwinView = Schemas['TwinView']
export type Registry = Schemas['Registry']
export type Game = Schemas['Game']

/** One event streamed by the agent (docs/plan/03, "Streaming and the agent timeline"). */
export type AgentEvent =
  | { kind: 'node'; node: string; status: 'start' | 'done' | 'error'; ms?: number }
  | { kind: 'decision'; node: string; decision_id: string; chosen: string; reason: string }
  | { kind: 'degraded'; what: string; from: string; to: string; node: string }
  | { kind: 'say'; text: string; node?: string; template?: string }
  | { kind: 'memory'; text: string }
  | { kind: 'session'; status: string; rounds: number }
  | { kind: 'interrupt'; id: string; payload: { type: 'exercise'; spec: ExerciseSpec } }
  | { kind: 'done'; waiting: boolean }
