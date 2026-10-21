import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Registry } from '../api/types'
import { GAMES } from '../games'
import { GameFrame } from '../taskhost/GameFrame'
import { useSession } from './useSession'

function greeting(now: Date): string {
  const h = now.getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

/** `?ask=...` starts the session with that request, as if the user had said it. */
function askFromUrl(): string | undefined {
  const ask = new URLSearchParams(window.location.search).get('ask')
  return ask?.trim() ? ask.trim() : undefined
}

export function App() {
  const { state, start, play, finish, resumeSaved, skipSaved } = useSession()
  const [registry, setRegistry] = useState<Registry | null>(null)

  useEffect(() => {
    api.registry().then(setRegistry, () => {
      setRegistry(null)
    })
  }, [])

  const skillNames = (gameId: string): string[] => {
    const game = registry?.games.find((g) => g.id === gameId)
    if (!game || !registry) return []
    return Object.keys(game.dims).map((d) => registry.dimensions.find((x) => x.id === d)?.name ?? d)
  }

  const game = state.spec ? GAMES[state.spec.game_id] : undefined
  const now = new Date()

  return (
    <main className="app">
      <header className="app__header">
        <p className="muted">
          {now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}
        </p>
        <h1>{greeting(now)}</h1>
      </header>

      {state.phase === 'home' && (
        <section className="card">
          <h2>Najma</h2>
          <p>
            A practice coach for how you focus, remember and reason. It doesn&apos;t assess medical
            or psychological conditions.
          </p>
          <button type="button" className="primary" onClick={() => void start(askFromUrl())}>
            Start a session
          </button>
        </section>
      )}

      {state.phase === 'resumable' && state.spec && (
        <section className="card" data-testid="resume">
          <h2>Welcome back</h2>
          <p>
            You were in the middle of {GAMES[state.spec.game_id]?.name ?? state.spec.game_id}.
            Resume or skip?
          </p>
          <div className="flex gap-2">
            <button type="button" className="primary" onClick={() => void resumeSaved()}>
              Resume
            </button>
            <button type="button" onClick={() => void skipSaved()}>
              Skip
            </button>
          </div>
        </section>
      )}

      {state.phase === 'starting' && <p className="card">Najma is choosing your first game…</p>}

      {state.phase === 'ready' && state.spec && (
        <section className="card" data-testid="suggestion">
          <h2>Next: {game?.name ?? state.spec.game_id}</h2>
          {state.reason && <p className="reason">{state.reason}</p>}
          {game ? (
            <button type="button" className="primary" onClick={play}>
              Let&apos;s go
            </button>
          ) : (
            <p role="alert">This game isn&apos;t ready in the browser yet.</p>
          )}
        </section>
      )}

      {state.phase === 'playing' && state.spec && state.sessionId && game && (
        <GameFrame
          key={state.spec.round_id}
          spec={state.spec}
          sessionId={state.sessionId}
          game={game}
          skills={skillNames(state.spec.game_id)}
          onFinish={finish}
        />
      )}

      {(state.phase === 'scoring' || state.phase === 'after' || state.phase === 'ended') && (
        <section className="card" data-testid="after-game">
          <h2>{state.phase === 'ended' ? 'Session done' : 'How that went'}</h2>
          {state.says.length === 0 && <p className="muted">Najma is looking at your round…</p>}
          <div className="coach" data-testid="coach">
            {state.says.map((text, i) => (
              <p key={i}>{text}</p>
            ))}
          </div>
          {state.phase === 'after' && state.spec && (
            <button type="button" className="primary" onClick={play}>
              Next game
            </button>
          )}
          {state.phase === 'ended' && (
            <button type="button" className="primary" onClick={() => void start()}>
              Start another session
            </button>
          )}
        </section>
      )}

      {state.phase === 'error' && (
        <p role="alert" className="card">
          Couldn&apos;t reach Najma: {state.error}
        </p>
      )}
    </main>
  )
}
