import { useCallback, useEffect, useRef, useState } from 'react'

import { api, ensureUser, getToken } from '../api/client'
import { SessionSocket } from '../api/session'
import type { AgentEvent, ExerciseSpec, RoundResult } from '../api/types'

export type Phase =
  'home' | 'resumable' | 'starting' | 'ready' | 'playing' | 'scoring' | 'after' | 'ended' | 'error'

export interface SessionState {
  phase: Phase
  sessionId: string | null
  spec: ExerciseSpec | null
  reason: string | null
  says: string[]
  timeline: AgentEvent[]
  error: string | null
  lastRoundId: string | null
  /** Najma's last call on how to go on, so the user can say whether it was right. */
  lastMonitor: { decisionId: string; chosen: string } | null
}

const INITIAL: SessionState = {
  phase: 'home',
  sessionId: null,
  spec: null,
  reason: null,
  says: [],
  timeline: [],
  error: null,
  lastRoundId: null,
  lastMonitor: null,
}

const SESSION_KEY = 'najma.session'

function remember(sessionId: string | null): void {
  try {
    if (sessionId) localStorage.setItem(SESSION_KEY, sessionId)
    else localStorage.removeItem(SESSION_KEY)
  } catch {
    // Private mode: no resume after a refresh.
  }
}

function remembered(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY)
  } catch {
    return null
  }
}

/** One practice session with Najma: start, play each exercise, resume the graph, read coaching. */
export function useSession() {
  const [state, setState] = useState<SessionState>(INITIAL)
  const socket = useRef<SessionSocket | null>(null)

  const handle = useCallback((event: AgentEvent) => {
    setState((s) => {
      const next = { ...s, timeline: [...s.timeline.slice(-199), event] }
      switch (event.kind) {
        case 'decision':
          if (event.node === 'monitor')
            return { ...next, lastMonitor: { decisionId: event.decision_id, chosen: event.chosen } }
          return event.node === 'plan_next' ? { ...next, reason: event.reason } : next
        case 'say':
          return { ...next, says: [...s.says, event.text] }
        case 'interrupt':
          return {
            ...next,
            spec: event.payload.spec,
            phase: s.phase === 'starting' ? 'ready' : s.phase === 'scoring' ? 'after' : s.phase,
          }
        case 'session':
          if (event.status !== 'ended') return next
          remember(null)
          return { ...next, phase: 'ended', spec: null }
        case 'done':
          return s.phase === 'scoring'
            ? { ...next, phase: event.waiting ? 'after' : 'ended' }
            : next
        default:
          return next
      }
    })
  }, [])

  const attach = useCallback(
    async (sessionId: string, token: string) => {
      socket.current?.close()
      const ws = new SessionSocket(sessionId, token)
      ws.onEvent(handle)
      socket.current = ws
      setState((s) => ({ ...s, sessionId }))
      await ws.connect()
    },
    [handle],
  )

  // A refresh or crash mid-game: the graph is still paused at `play`, so offer to pick up (UW6).
  useEffect(() => {
    const sessionId = remembered()
    if (!sessionId || !getToken()) return
    api.pending(sessionId).then(
      ({ pending }) => {
        if (pending?.kind !== 'interrupt') {
          remember(null)
          return
        }
        setState((s) => ({ ...s, phase: 'resumable', sessionId, spec: pending.payload.spec }))
      },
      () => {
        remember(null)
      },
    )
  }, [])

  const start = useCallback(
    async (message?: string) => {
      setState({ ...INITIAL, phase: 'starting' })
      try {
        const token = await ensureUser()
        const started = await api.startSession('ui', message)
        for (const event of started.events) handle(event)
        remember(started.session_id)
        await attach(started.session_id, token)
      } catch (e) {
        setState((s) => ({
          ...s,
          phase: 'error',
          error: e instanceof Error ? e.message : String(e),
        }))
      }
    },
    [handle, attach],
  )

  const resumeSaved = useCallback(async () => {
    const token = getToken()
    if (!state.sessionId || !token) return
    await attach(state.sessionId, token)
    setState((s) => ({ ...s, phase: 'ready' }))
  }, [attach, state.sessionId])

  const skipSaved = useCallback(async () => {
    const token = getToken()
    const spec = state.spec
    if (!state.sessionId || !token || !spec) return
    await attach(state.sessionId, token)
    const now = new Date().toISOString()
    setState((s) => ({ ...s, phase: 'scoring', spec: null, says: [] }))
    await socket.current?.resume({
      round_id: spec.round_id,
      game_id: spec.game_id,
      status: 'stopped',
      stop_reason: 'user',
      trial_count: 0,
      metrics: {},
      final_level: spec.level,
      started_at: now,
      ended_at: now,
      behaviour: null,
    })
  }, [attach, state.sessionId, state.spec])

  const play = useCallback(() => {
    setState((s) => ({ ...s, phase: 'playing', says: [] }))
  }, [])

  const finish = useCallback((result: RoundResult) => {
    setState((s) => ({
      ...s,
      phase: 'scoring',
      says: [],
      spec: null,
      lastRoundId: result.round_id,
      lastMonitor: null,
    }))
    void socket.current?.resume(result)
  }, [])

  useEffect(() => () => socket.current?.close(), [])

  return { state, start, play, finish, resumeSaved, skipSaved }
}
