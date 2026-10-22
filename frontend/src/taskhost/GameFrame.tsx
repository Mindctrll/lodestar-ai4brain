import { useEffect, useRef, useState, type ReactNode } from 'react'

import { useCameraCues } from '../affect/camera'
import type { ExerciseSpec, RoundResult } from '../api/types'
import { coachSays, stopSpeaking } from '../voice/tts'
import type { GameModule, Score } from './types'
import { TaskHost, type TaskControls } from './TaskHost'

interface Props {
  spec: ExerciseSpec
  sessionId: string
  game: GameModule
  skills: string[]
  onFinish: (result: RoundResult, score: Score) => void
  reason?: ReactNode
}

/** The frame every game shares (docs/plan/06): header, stage, and pause / too hard / quit. */
export function GameFrame({ spec, sessionId, game, skills, onFinish, reason }: Props) {
  const [started, setStarted] = useState(false)
  const [paused, setPaused] = useState(false)
  const [struggling, setStruggling] = useState(false)
  const [progress, setProgress] = useState<[number, number]>([0, 0])
  const controls = useRef<TaskControls | null>(null)
  const frame = useRef<HTMLElement>(null)
  useCameraCues(started) // only with the camera switch on; frames never leave the browser

  // The game opens inside the conversation: bring it into view.
  useEffect(() => {
    frame.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  // Voice coaching (docs/plan/12): when Lodestar speaks, it reads the instructions out loud.
  useEffect(() => {
    coachSays(`${game.name}. ${game.instructions}`)
    return stopSpeaking
  }, [game])

  return (
    <section className="game-frame" aria-label={game.name} ref={frame}>
      <header className="game-frame__header">
        <div className="game-frame__title">
          <p className="eyebrow">
            <span className="live-dot" aria-hidden="true" />
            Now playing
          </p>
          <h2>{game.name}</h2>
        </div>
        <ul className="chips" aria-label="Skills">
          {skills.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
        {started && (
          <p className="game-frame__progress" aria-live="polite">
            {progress[0]} / {progress[1]}
          </p>
        )}
      </header>
      <div className="game-frame__bar" aria-hidden="true">
        <span
          style={{
            width: `${String(progress[1] ? Math.round((progress[0] / progress[1]) * 100) : 0)}%`,
          }}
        />
      </div>

      {!started ? (
        <div className="game-frame__intro">
          {reason && <p className="game-frame__reason">{reason}</p>}
          <p className="game-frame__how">{game.instructions}</p>
          <p className="game-frame__keys">{game.keysHint}</p>
          {spec.practice_trials > 0 && (
            <p className="muted">The first {spec.practice_trials} are practice.</p>
          )}
          <button
            type="button"
            className="primary"
            onClick={() => {
              stopSpeaking()
              coachSays('Ready. Go!')
              setStarted(true)
            }}
            autoFocus
          >
            Start
          </button>
        </div>
      ) : (
        <TaskHost
          spec={spec}
          sessionId={sessionId}
          game={game}
          onFinish={onFinish}
          onProgress={(done, total) => {
            setProgress([done, total])
          }}
          onStruggle={() => {
            controls.current?.pause()
            setStruggling(true)
          }}
          controlsRef={controls}
        />
      )}

      {struggling && (
        <div
          className="game-frame__offer"
          role="dialog"
          aria-label="Easier?"
          data-testid="easier-offer"
        >
          <p>That looked tough. Want it a bit easier?</p>
          <button
            type="button"
            className="primary"
            onClick={() => {
              setStruggling(false)
              controls.current?.stop('eased')
            }}
          >
            Yes, easier
          </button>
          <button
            type="button"
            onClick={() => {
              setStruggling(false)
              controls.current?.resume()
            }}
          >
            Keep going
          </button>
        </div>
      )}

      {started && (
        <footer className="game-frame__footer">
          <button
            type="button"
            className="ghost small"
            onClick={() => {
              if (paused) controls.current?.resume()
              else controls.current?.pause()
              setPaused(!paused)
            }}
          >
            {paused ? 'Resume' : 'Pause'}
          </button>
          <button
            type="button"
            className="ghost small"
            onClick={() => controls.current?.stop('eased')}
          >
            Too hard?
          </button>
          <button
            type="button"
            className="ghost small"
            onClick={() => controls.current?.stop('stopped')}
          >
            Quit
          </button>
        </footer>
      )}
    </section>
  )
}
