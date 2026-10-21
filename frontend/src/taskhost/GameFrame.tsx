import { useEffect, useRef, useState, type ReactNode } from 'react'

import { useCameraCues } from '../affect/camera'
import type { ExerciseSpec, RoundResult } from '../api/types'
import { coachSays, stopSpeaking } from '../voice/tts'
import type { GameModule } from './types'
import { TaskHost, type TaskControls } from './TaskHost'

interface Props {
  spec: ExerciseSpec
  sessionId: string
  game: GameModule
  skills: string[]
  onFinish: (result: RoundResult) => void
  reason?: ReactNode
}

/** The frame every game shares (docs/plan/06): header, stage, and pause / too hard / quit. */
export function GameFrame({ spec, sessionId, game, skills, onFinish, reason }: Props) {
  const [started, setStarted] = useState(false)
  const [paused, setPaused] = useState(false)
  const [struggling, setStruggling] = useState(false)
  const [progress, setProgress] = useState<[number, number]>([0, 0])
  const controls = useRef<TaskControls | null>(null)
  useCameraCues(started) // only with the camera switch on; frames never leave the browser

  // Voice coaching (docs/plan/12): when Najma speaks, she reads the instructions out loud.
  useEffect(() => {
    coachSays(`${game.name}. ${game.instructions}`)
    return stopSpeaking
  }, [game])

  return (
    <section className="game-frame" aria-label={game.name}>
      <header className="game-frame__header">
        <div>
          <h2>{game.name}</h2>
          <ul className="chips" aria-label="Skills">
            {skills.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
        {started && (
          <p className="game-frame__progress" aria-live="polite">
            {progress[0]} / {progress[1]}
          </p>
        )}
      </header>

      {!started ? (
        <div className="game-frame__intro">
          {reason && <p className="game-frame__reason">{reason}</p>}
          <p>{game.instructions}</p>
          <p className="muted">{game.keysHint}</p>
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
            onClick={() => {
              if (paused) controls.current?.resume()
              else controls.current?.pause()
              setPaused(!paused)
            }}
          >
            {paused ? 'Resume' : 'Pause'}
          </button>
          <button type="button" onClick={() => controls.current?.stop('eased')}>
            Too hard?
          </button>
          <button type="button" onClick={() => controls.current?.stop('stopped')}>
            Quit
          </button>
        </footer>
      )}
    </section>
  )
}
