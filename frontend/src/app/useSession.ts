import { useCallback, useEffect, useRef, useState } from 'react'

import { api, ensureUser, getToken } from '../api/client'
import { SessionSocket } from '../api/session'
import type { AgentEvent, ConfirmRequest, ExerciseSpec, RoundResult } from '../api/types'

export type Phase =
  | 'home'
  | 'resumable'
  | 'starting'
  | 'chatting'
  | 'ready'
  | 'playing'
  | 'scoring'
  | 'after'
  | 'ended'
  | 'error'

/** A line Najma says, with its citation map ([D1] -> decision id). */
export interface Said {
  text: string
  refs?: Record<string, string> | undefined
}

/** Something the agent can open beside its reply. */
export type Surface = 'twin' | 'goals' | 'progress' | 'experiments'

/** One entry in the conversation. Games, results and the agent's surfaces live in the thread
 * next to the words, in the order they happened. */
export type FeedItem =
  | ({ kind: 'you' | 'najma' } & Said)
  /** An exercise Najma picked: a suggestion, then the game itself, then a short record. */
  | { kind: 'pick'; spec: ExerciseSpec; reason: string | null; decision: string | null }
  /** The coach after a round, with the mood buttons. */
  | { kind: 'result'; roundId: string | null; says: Said[] }
  | { kind: 'show'; what: Surface; dim: string | null }
  | { kind: 'ended' }

/** route_intent's reading of a turn, and the surface that goes with it. */
function surfaceFor(intent: string, tool: string | null): Surface | null {
  if (intent === 'twin_chat' || tool === 'read_profile') return 'twin'
  if (intent === 'goal') return 'goals'
  if (intent === 'experiment') return 'experiments'
  if (tool === 'get_history') return 'progress'
  return null
}

export interface SessionState {
  phase: Phase
  sessionId: string | null
  spec: ExerciseSpec | null
  reason: string | null
  /** The pick behind `reason`, for its "why" card. */
  reasonDecision: string | null
  feed: FeedItem[]
  /** A change Najma wants to make, waiting for a yes or no. */
  confirm: ConfirmRequest | null
  /** Najma is working on a reply. */
  busy: boolean
  timeline: AgentEvent[]
  error: string | null
  lastRoundId: string | null
  /** Najma's last call on how to go on, so the user can say whether it was right. */
  lastMonitor: { decisionId: string; chosen: string } | null
  /** A surface to open once this turn is answered (and any yes-or-no question settled). */
  surface: { what: Surface; dim: string | null } | null
}

const INITIAL: SessionState = {
  phase: 'home',
  sessionId: null,
  spec: null,
  reason: null,
  reasonDecision: null,
  feed: [],
  confirm: null,
  busy: false,
  timeline: [],
  error: null,
  lastRoundId: null,
  lastMonitor: null,
  surface: null,
}

/** Najma's words in the feed, in order (chat replies and the after-game coach). */
export function najmaLines(feed: FeedItem[]): string[] {
  return feed.flatMap((item) =>
    item.kind === 'najma'
      ? [item.text]
      : item.kind === 'result'
        ? item.says.map((l) => l.text)
        : [],
  )
}

/** Add a line to the newest result card. */
function addToResult(feed: FeedItem[], line: Said): FeedItem[] {
  const at = feed.findLastIndex((i) => i.kind === 'result')
  const item = feed[at]
  if (item?.kind !== 'result') return [...feed, { kind: 'najma', ...line }]
  return feed.map((x, i) => (i === at ? { ...item, says: [...item.says, line] } : x))
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

/** `?session=<id>`: the CLI hands over a game that plays only in the browser (UW19). The id
 * leaves the address bar at once, and the session is picked up like one paused by a refresh. */
function handedOver(): string | null {
  const url = new URL(window.location.href)
  const sessionId = url.searchParams.get('session')
  if (!sessionId) return null
  url.searchParams.delete('session')
  window.history.replaceState(null, '', url.toString())
  remember(sessionId)
  return sessionId
}

const WAITING_FOR_A_GAME: Phase[] = ['home', 'starting', 'chatting', 'ready', 'ended']

/** One practice session with Najma: start, play each exercise, resume the graph, read coaching,
 * and talk to Najma in between. */
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
          return event.node === 'plan_next'
            ? { ...next, reason: event.reason, reasonDecision: event.decision_id }
            : next
        case 'intent': {
          const what = surfaceFor(event.intent, event.tool)
          return what ? { ...next, surface: { what, dim: event.dim } } : next
        }
        case 'say': {
          const line = { text: event.text, refs: event.refs }
          // After a game the coach (and a story's ending) speaks in the result card; everything
          // else is conversation.
          const after = event.node === 'coach' || event.node === 'story'
          if (after && (s.phase === 'scoring' || s.phase === 'after'))
            return { ...next, feed: addToResult(s.feed, line) }
          return { ...next, feed: [...s.feed, { kind: 'najma', ...line }] }
        }
        case 'interrupt': {
          if (event.payload.type === 'confirm')
            return { ...next, confirm: event.payload, busy: false }
          // The same pick again (a reconnect, or a chat turn while it waits): keep the one shown.
          const spec = event.payload.spec
          const shown = s.feed.some((i) => i.kind === 'pick' && i.spec.round_id === spec.round_id)
          return {
            ...next,
            spec: event.payload.spec,
            busy: false,
            feed: shown
              ? s.feed
              : [
                  ...s.feed,
                  {
                    kind: 'pick',
                    spec: event.payload.spec,
                    reason: s.reason,
                    decision: s.reasonDecision,
                  },
                ],
            phase: WAITING_FOR_A_GAME.includes(s.phase)
              ? 'ready'
              : s.phase === 'scoring'
                ? 'after'
                : s.phase,
          }
        }
        case 'session':
          if (event.status !== 'ended') return next
          remember(null)
          return { ...next, phase: 'ended', spec: null, feed: [...s.feed, { kind: 'ended' }] }
        case 'done': {
          // The turn is answered: open its surface, unless a yes-or-no question is still open.
          const shown =
            s.surface && !s.confirm
              ? {
                  surface: null,
                  feed: [
                    ...s.feed,
                    { kind: 'show' as const, what: s.surface.what, dim: s.surface.dim },
                  ],
                }
              : {}
          if (s.phase === 'scoring')
            return { ...next, ...shown, busy: false, phase: event.waiting ? 'after' : 'ended' }
          if (s.phase === 'starting' && !event.waiting)
            return { ...next, ...shown, busy: false, phase: 'chatting' }
          return { ...next, ...shown, busy: false }
        }
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
    const sessionId = handedOver() ?? remembered()
    if (!sessionId || !getToken()) return
    api.pending(sessionId).then(
      ({ pending }) => {
        if (pending?.kind !== 'interrupt' || pending.payload.type !== 'exercise') {
          remember(null)
          return
        }
        const spec = pending.payload.spec
        setState((s) => ({ ...s, phase: 'resumable', sessionId, spec }))
      },
      () => {
        remember(null)
      },
    )
  }, [])

  const start = useCallback(
    async (message?: string, trigger: 'ui' | 'voice' = 'ui') => {
      setState({
        ...INITIAL,
        phase: 'starting',
        busy: true,
        feed: message ? [{ kind: 'you', text: message }] : [],
      })
      try {
        const token = await ensureUser()
        const started = await api.startSession(trigger, message)
        for (const event of started.events) handle(event)
        remember(started.session_id)
        await attach(started.session_id, token)
      } catch (e) {
        setState((s) => ({
          ...s,
          phase: 'error',
          busy: false,
          error: e instanceof Error ? e.message : String(e),
        }))
      }
    },
    [handle, attach],
  )

  /** Say something to Najma: starts a session if there isn't a live one. */
  const send = useCallback(
    async (text: string, trigger: 'ui' | 'voice' = 'ui') => {
      const message = text.trim()
      if (!message) return
      if (!state.sessionId || state.phase === 'ended' || state.phase === 'home') {
        await start(message, trigger)
        return
      }
      setState((s) => ({
        ...s,
        busy: true,
        confirm: null,
        feed: [...s.feed, { kind: 'you', text: message }],
      }))
      await socket.current?.say(message)
    },
    [start, state.sessionId, state.phase],
  )

  const answer = useCallback(async (confirmed: boolean) => {
    setState((s) => ({
      ...s,
      busy: true,
      confirm: null,
      feed: [...s.feed, { kind: 'you', text: confirmed ? 'Yes' : 'No' }],
    }))
    await socket.current?.confirm(confirmed)
  }, [])

  /** From a conversation, ask Najma to pick a game. */
  const nextGame = useCallback(async () => {
    setState((s) => ({ ...s, busy: true }))
    await socket.current?.next()
  }, [])

  const resumeSaved = useCallback(async () => {
    const token = getToken()
    if (!state.sessionId || !token) return
    await attach(state.sessionId, token)
    setState((s) => ({
      ...s,
      phase: 'ready',
      feed: s.spec
        ? [...s.feed, { kind: 'pick', spec: s.spec, reason: null, decision: null }]
        : s.feed,
    }))
  }, [attach, state.sessionId])

  const skipSaved = useCallback(async () => {
    const token = getToken()
    const spec = state.spec
    if (!state.sessionId || !token || !spec) return
    await attach(state.sessionId, token)
    const now = new Date().toISOString()
    setState((s) => ({
      ...s,
      phase: 'scoring',
      spec: null,
      feed: [...s.feed, { kind: 'result', roundId: spec.round_id, says: [] }],
    }))
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
    setState((s) => ({ ...s, phase: 'playing' }))
  }, [])

  const finish = useCallback((result: RoundResult) => {
    setState((s) => ({
      ...s,
      phase: 'scoring',
      spec: null,
      feed: [...s.feed, { kind: 'result', roundId: result.round_id, says: [] }],
      lastRoundId: result.round_id,
      lastMonitor: null,
    }))
    void socket.current?.resume(result)
  }, [])

  useEffect(() => () => socket.current?.close(), [])

  return { state, start, send, answer, nextGame, play, finish, resumeSaved, skipSaved }
}
