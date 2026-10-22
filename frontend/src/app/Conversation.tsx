import { useEffect, useRef, useState, type ReactNode } from 'react'

import { api } from '../api/client'
import type { GoalView, ProgressView, Registry, TwinView } from '../api/types'
import { Goals } from '../dashboard/Goals'
import { NightSky } from '../dashboard/NightSky'
import { GAMES } from '../games'
import { GameFrame } from '../taskhost/GameFrame'
import { Cited } from './Cited'
import type { FeedItem, Surface, useSession } from './useSession'

export type Panel = 'twin' | 'progress' | 'experiments' | 'agent' | 'acs' | 'settings'

/** `?ask=...` starts the session with that request, as if the user had said it. */
function askFromUrl(): string | undefined {
  const ask = new URLSearchParams(window.location.search).get('ask')
  return ask?.trim() ? ask.trim() : undefined
}

function greeting(now: Date): string {
  const h = now.getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

function Star({ size = 28 }: { size?: number }) {
  return (
    <span className="avatar" aria-hidden="true" style={{ width: size, height: size }}>
      <svg viewBox="0 0 24 24" width={size * 0.55} height={size * 0.55}>
        <path d="M12 1.5l2.6 7.9 7.9 2.6-7.9 2.6L12 22.5l-2.6-7.9L1.5 12l7.9-2.6z" />
      </svg>
    </span>
  )
}

function AfterGameLabels({
  sessionId,
  roundId,
  monitor,
}: {
  sessionId: string
  roundId: string | null
  monitor: { decisionId: string; chosen: string } | null
}) {
  const [mood, setMood] = useState<string | null>(null)
  const [answered, setAnswered] = useState(false)
  const send = (kind: 'mood' | 'was_i_right', value: string, extra: object) => {
    void api.label({ session_id: sessionId, kind, value, ...extra }).catch(() => undefined)
  }
  const guessed = monitor && (monitor.chosen === 'ease' || monitor.chosen === 'break')
  return (
    <div className="labels">
      <p className="eyebrow">How did that feel?</p>
      <div className="mood" role="group" aria-label="Mood">
        {(
          [
            ['good', '😀 Good'],
            ['ok', '😐 OK'],
            ['tough', '😣 Tough'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            className="chip"
            aria-pressed={mood === value}
            disabled={mood !== null}
            onClick={() => {
              setMood(value)
              send('mood', value, roundId ? { round_id: roundId } : {})
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {guessed && !answered && (
        <p className="was-i-right">
          I thought that one was hard for you. Was I right?{' '}
          <button
            type="button"
            className="chip"
            onClick={() => {
              setAnswered(true)
              send('was_i_right', 'yes', { decision_id: monitor.decisionId })
            }}
          >
            Yes
          </button>{' '}
          <button
            type="button"
            className="chip"
            onClick={() => {
              setAnswered(true)
              send('was_i_right', 'no', { decision_id: monitor.decisionId })
            }}
          >
            No
          </button>
        </p>
      )}
    </div>
  )
}

/** A surface the agent opened beside its reply: a glance, with a way into the full panel. */
function SurfaceCard({
  what,
  dim,
  registry,
  twin,
  goals,
  progress,
  onOpen,
}: {
  what: Surface
  dim: string | null
  registry: Registry | null
  twin: TwinView | null
  goals: GoalView[]
  progress: ProgressView | null
  onOpen: (panel: Panel, dim?: string) => void
}) {
  const [experiments, setExperiments] = useState<Awaited<ReturnType<typeof api.experiments>>>([])
  useEffect(() => {
    if (what === 'experiments') api.experiments().then(setExperiments, () => undefined)
  }, [what])

  let body: ReactNode = null
  let open: { label: string; panel: Panel } = { label: 'Open', panel: 'twin' }
  if (what === 'twin' && registry && twin) {
    body = (
      <NightSky
        registry={registry}
        dims={twin.dims}
        compact
        testId="night-sky-inline"
        onSelect={(d) => {
          onOpen('twin', d)
        }}
      />
    )
    open = { label: dim ? 'See this skill' : 'See every skill', panel: 'twin' }
  } else if (what === 'goals') {
    body = <Goals goals={goals} testId="goals-inline" />
    open = { label: 'Open charts', panel: 'progress' }
  } else if (what === 'progress' && progress) {
    body = (
      <ul className="stats">
        <li>
          <strong>{progress.stats.streak_days}</strong>
          <span>day streak</span>
        </li>
        <li>
          <strong>{progress.stats.rounds_this_week}</strong>
          <span>rounds this week</span>
        </li>
        <li>
          <strong>
            {progress.stats.skills_measured}/{progress.stats.skills_total}
          </strong>
          <span>skills measured</span>
        </li>
      </ul>
    )
    open = { label: 'Open charts', panel: 'progress' }
  } else if (what === 'experiments') {
    body =
      experiments.length === 0 ? (
        <p className="muted">No experiments yet.</p>
      ) : (
        <ul className="lines">
          {experiments.slice(0, 3).map((e) => (
            <li key={e.exp_id}>
              <strong>{e.hypothesis}</strong>{' '}
              <span className="muted">
                ·{' '}
                {Object.entries(e.progress)
                  .map(([c, n]) => `${c} ${String(n)}/${String(e.sessions_per_condition)}`)
                  .join(', ')}
              </span>
            </li>
          ))}
        </ul>
      )
    open = { label: 'Open the lab', panel: 'experiments' }
  }
  if (!body) return null
  const title = {
    twin: 'Your Brain Twin',
    goals: 'Goals',
    progress: 'Your week',
    experiments: 'Lab',
  }[what]
  return (
    <article className="turn-card surface" data-surface={what}>
      <header className="turn-card__head">
        <p className="eyebrow">{title}</p>
        <button
          type="button"
          className="ghost small"
          onClick={() => {
            onOpen(open.panel, what === 'twin' && dim ? dim : undefined)
          }}
        >
          {open.label} ↗
        </button>
      </header>
      {body}
    </article>
  )
}

/** The conversation with Najma, which is the whole app: Najma talks, and games, results and the
 * Twin open right here in the thread (docs/plan/03). Panels hold the long-form views. */
export function Conversation({
  session,
  registry,
  twin,
  goals,
  progress,
  setWhy,
  onOpen,
}: {
  session: ReturnType<typeof useSession>
  registry: Registry | null
  twin: TwinView | null
  goals: GoalView[]
  progress: ProgressView | null
  setWhy: (decisionId: string) => void
  onOpen: (panel: Panel, dim?: string) => void
}) {
  const { state, start, answer, play, finish, resumeSaved, skipSaved } = session
  const end = useRef<HTMLDivElement>(null)
  const now = new Date()

  // Follow the conversation as it grows.
  const size = state.feed.length + (state.confirm ? 1 : 0) + (state.busy ? 1 : 0)
  useEffect(() => {
    // A game scrolls itself into view instead.
    if (size > 0 && state.phase !== 'playing')
      end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [size, state.phase])

  const skillNames = (gameId: string): string[] => {
    const g = registry?.games.find((x) => x.id === gameId)
    if (!g || !registry) return []
    return Object.keys(g.dims).map((d) => registry.dimensions.find((x) => x.id === d)?.name ?? d)
  }
  const livePick = state.spec
    ? state.feed.findLastIndex((i) => i.kind === 'pick' && i.spec.round_id === state.spec?.round_id)
    : -1
  const liveResult = ['scoring', 'after', 'ended'].includes(state.phase)
    ? state.feed.findLastIndex((i) => i.kind === 'result')
    : -1
  const lastNajma = state.feed.findLast((i) => i.kind === 'najma')

  const render = (item: FeedItem, i: number): ReactNode => {
    switch (item.kind) {
      case 'you':
        return <p className="bubble">{item.text}</p>
      case 'najma':
        return (
          <div className="said">
            <Star />
            <p>
              <Cited text={item.text} refs={item.refs} onWhy={setWhy} />
            </p>
          </div>
        )
      case 'pick': {
        const game = GAMES[item.spec.game_id]
        const name = game?.name ?? item.spec.game_id
        if (i !== livePick) {
          const played = state.feed.some(
            (x) => x.kind === 'result' && x.roundId === item.spec.round_id,
          )
          return (
            <p className="record">
              <span aria-hidden="true">{played ? '✓' : '·'}</span> {played ? 'Played' : 'Offered'}{' '}
              <strong>{name}</strong>
            </p>
          )
        }
        if (state.phase === 'playing' && state.sessionId && game)
          return (
            <GameFrame
              key={item.spec.round_id}
              spec={item.spec}
              sessionId={state.sessionId}
              game={game}
              skills={skillNames(item.spec.game_id)}
              reason={item.spec.reason}
              onFinish={finish}
            />
          )
        return (
          <article className="turn-card pick" data-testid="suggestion">
            <p className="eyebrow">{state.phase === 'after' ? 'Up next' : 'Najma picked'}</p>
            <h2>{name}</h2>
            <ul className="chips" aria-label="Skills">
              {skillNames(item.spec.game_id).map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
            {item.reason && (
              <p className="reason">
                {item.reason}{' '}
                {item.decision && (
                  <button
                    type="button"
                    className="link"
                    onClick={() => {
                      if (item.decision) setWhy(item.decision)
                    }}
                  >
                    Why?
                  </button>
                )}
              </p>
            )}
            {game ? (
              <button type="button" className="primary" onClick={play}>
                {state.phase === 'after' ? 'Next game' : "Let's go"}
              </button>
            ) : (
              <p role="alert">This game isn&apos;t ready in the browser yet.</p>
            )}
          </article>
        )
      }
      case 'result': {
        const live = i === liveResult
        const round = state.feed.findLast(
          (x): x is Extract<FeedItem, { kind: 'pick' }> =>
            x.kind === 'pick' && x.spec.round_id === item.roundId,
        )
        return (
          <article
            className={`turn-card result${live ? '' : ' result--past'}`}
            data-testid={live ? 'after-game' : undefined}
          >
            <header className="turn-card__head">
              <Star size={24} />
              <p className="eyebrow">
                {round ? `${GAMES[round.spec.game_id]?.name ?? round.spec.game_id} · ` : ''}round
                done
              </p>
            </header>
            {live && <h2>How that went</h2>}
            {item.says.length === 0 && <p className="muted thinking">Looking at your round</p>}
            <div className="coach" data-testid={live ? 'coach' : undefined}>
              {item.says.map((line, j) => (
                <p key={j}>
                  <Cited text={line.text} refs={line.refs} onWhy={setWhy} />
                </p>
              ))}
            </div>
            {live && state.sessionId && item.says.length > 0 && (
              <AfterGameLabels
                key={state.lastRoundId ?? 'none'}
                sessionId={state.sessionId}
                roundId={state.lastRoundId}
                monitor={state.lastMonitor}
              />
            )}
          </article>
        )
      }
      case 'show':
        return (
          <SurfaceCard
            what={item.what}
            dim={item.dim}
            registry={registry}
            twin={twin}
            goals={goals}
            progress={progress}
            onOpen={onOpen}
          />
        )
      case 'ended':
        return (
          <article className="turn-card ended">
            <p className="eyebrow">Session done</p>
            <p>Nice work. Come back whenever you like; I&apos;ll pick up from here.</p>
            {i === state.feed.length - 1 && state.phase === 'ended' && (
              <button type="button" className="primary" onClick={() => void start()}>
                Start another session
              </button>
            )}
          </article>
        )
    }
  }

  return (
    <section className="thread" data-testid="chat" aria-label="Talk to Najma">
      <header className="hero">
        <p className="eyebrow">
          {now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}
        </p>
        <h1>{greeting(now)}</h1>
        {progress && (
          <ul className="pills" aria-label="Your week">
            <li>
              <strong>{progress.stats.streak_days}</strong> day streak
            </li>
            <li>
              <strong>{progress.stats.rounds_this_week}</strong> rounds this week
            </li>
            <li>
              <strong>
                {progress.stats.skills_measured}/{progress.stats.skills_total}
              </strong>{' '}
              skills measured
            </li>
          </ul>
        )}
        {state.phase === 'home' && (
          <div className="hero__start" data-testid="start">
            <div className="said">
              <Star />
              <p>
                I&apos;m Najma, a practice coach for how you focus, remember and reason. Tell me how
                you&apos;re doing, ask me anything, or let me pick a game. I don&apos;t assess
                medical or psychological conditions.
              </p>
            </div>
            <div className="actions">
              <button type="button" className="primary" onClick={() => void start(askFromUrl())}>
                Start a session
              </button>
              <button
                type="button"
                title="A short mystery where each chapter is one of the games"
                onClick={() => void start('play the Detective story')}
              >
                Detective story
              </button>
            </div>
          </div>
        )}
      </header>

      <ol className="feed">
        {state.feed.map((item, i) => (
          <li
            key={i}
            className={`feed__item feed__item--${item.kind}${item.kind === 'najma' && state.feed[i - 1]?.kind === 'najma' ? ' feed__item--cont' : ''}${i === livePick && state.phase === 'playing' ? ' feed__item--playing' : ''}`}
          >
            {render(item, i)}
          </li>
        ))}
      </ol>

      {state.phase === 'resumable' && state.spec && (
        <article className="turn-card" data-testid="resume">
          <p className="eyebrow">Welcome back</p>
          <p>
            You were in the middle of {GAMES[state.spec.game_id]?.name ?? state.spec.game_id}.
            Resume or skip?
          </p>
          <div className="actions">
            <button type="button" className="primary" onClick={() => void resumeSaved()}>
              Resume
            </button>
            <button type="button" onClick={() => void skipSaved()}>
              Skip
            </button>
          </div>
        </article>
      )}

      {state.confirm && (
        <article
          className="turn-card confirm"
          role="dialog"
          aria-label="Najma asks"
          data-testid="confirm"
        >
          <div className="said">
            <Star />
            <p>
              <Cited text={state.confirm.prompt} />
            </p>
          </div>
          <div className="actions">
            <button type="button" className="primary" onClick={() => void answer(true)}>
              Yes
            </button>
            <button type="button" onClick={() => void answer(false)}>
              No
            </button>
          </div>
        </article>
      )}

      {(state.busy || state.phase === 'starting') && (
        <div className="said said--busy">
          <Star />
          <p className="thinking">
            {state.phase === 'starting' && state.feed.length <= 1
              ? 'Choosing your first game'
              : 'Thinking'}
          </p>
        </div>
      )}

      {state.phase === 'error' && (
        <p role="alert" className="turn-card">
          Couldn&apos;t reach Najma: {state.error}
        </p>
      )}

      <p className="sr-only" aria-live="polite">
        {lastNajma?.kind === 'najma' ? lastNajma.text : ''}
      </p>
      <div ref={end} className="thread__end" />
    </section>
  )
}
