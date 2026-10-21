import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import { listen, speechEngine, type Listening } from './speech'

type OrbState = 'idle' | 'consent' | 'listening' | 'transcribing'

/** Tap-to-talk (docs/plan/12; UW4): tap the orb or press Alt+V, speak, tap again. What was heard
 * shows as a caption before it is sent. The microphone switch is asked for in place the first
 * time. */
export function Orb({ onTranscript }: { onTranscript: (text: string) => void }) {
  const [state, setState] = useState<OrbState>('idle')
  const [caption, setCaption] = useState('')
  const [error, setError] = useState<string | null>(null)
  const turn = useRef<Listening | null>(null)
  const engine = speechEngine()

  const begin = useCallback(async () => {
    setError(null)
    setCaption('')
    try {
      const consent = await api.consent()
      if (!consent.switches.some((s) => s.id === 'microphone' && s.granted)) {
        setState('consent')
        return
      }
      turn.current = await listen(engine, setCaption)
      setState('listening')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setState('idle')
    }
  }, [engine])

  const end = useCallback(async () => {
    const current = turn.current
    turn.current = null
    if (!current) return
    setState('transcribing')
    try {
      const text = (await current.stop()).trim()
      setCaption(text)
      setState('idle')
      if (text) onTranscript(text)
      else setError("I didn't catch that. Try again?")
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setState('idle')
    }
  }, [onTranscript])

  const toggle = useCallback(() => {
    if (state === 'listening') void end()
    else if (state === 'idle') void begin()
  }, [state, begin, end])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.key.toLowerCase() === 'v') {
        e.preventDefault()
        toggle()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
    }
  }, [toggle])

  useEffect(() => () => turn.current?.cancel(), [])

  const label =
    state === 'listening'
      ? 'Listening. Tap to send'
      : state === 'transcribing'
        ? 'Working out what you said'
        : 'Tap to talk (Alt+V)'

  return (
    <section className="card orb-card" data-testid="voice">
      <button
        type="button"
        className={`orb orb--${state}`}
        aria-label={label}
        aria-pressed={state === 'listening'}
        disabled={state === 'transcribing' || state === 'consent'}
        onClick={toggle}
      >
        <span aria-hidden="true" />
      </button>
      <div className="orb__text">
        <p className="muted small">{label}</p>
        <p className="orb__caption" aria-live="polite" data-testid="voice-caption">
          {caption}
        </p>
        {state === 'consent' && (
          <div className="confirm" role="dialog" aria-label="Turn on the microphone">
            <p>
              To listen, Najma needs the microphone switch.{' '}
              {engine === 'browser'
                ? "Your browser's speech recognition may send the audio to its maker."
                : 'Speech is turned into text on this server, and the audio is not kept.'}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                className="primary"
                onClick={() => {
                  void api.setConsent('microphone', true).then(() => {
                    setState('idle')
                    void begin()
                  })
                }}
              >
                Turn on the microphone
              </button>
              <button
                type="button"
                onClick={() => {
                  setState('idle')
                }}
              >
                Not now
              </button>
            </div>
          </div>
        )}
        {error && <p role="alert">{error}</p>}
      </div>
    </section>
  )
}
