import { useCallback, useEffect, useRef, useState } from 'react'

import { listenWithTone } from '../affect/voiceTone'
import { api } from '../api/client'
import { speechEngine, type Listening } from './speech'
import { startWake, WAKE_LABEL, wakeSetup } from './wake'

type OrbState = 'idle' | 'consent' | 'listening' | 'transcribing'

/** Tap-to-talk (docs/plan/12; UW4): tap the orb or press Alt+V, speak, tap again. What was heard
 * shows as a caption before it is sent. The microphone switch is asked for in place the first
 * time. With a wake word set up in Settings, "Hey Lodestar" starts a turn that ends by itself after
 * a pause; if the wake word can't start, tap-to-talk is unchanged. */
export function Orb({ onTranscript }: { onTranscript: (text: string) => void }) {
  const [state, setState] = useState<OrbState>('idle')
  const [caption, setCaption] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [wake, setWake] = useState<'off' | 'on' | 'failed'>('off')
  const turn = useRef<Listening | null>(null)
  const engine = speechEngine()

  // The latest onTranscript, so `end` (and the wake word, which uses it) stays the same.
  const heard = useRef(onTranscript)
  useEffect(() => {
    heard.current = onTranscript
  })

  const end = useCallback(async () => {
    const current = turn.current
    turn.current = null
    if (!current) return
    setState('transcribing')
    try {
      const text = (await current.stop()).trim()
      setCaption(text)
      setState('idle')
      if (text) heard.current(text)
      else setError("I didn't catch that. Try again?")
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setState('idle')
    }
  }, [])

  const begin = useCallback(
    async (handsFree = false) => {
      setError(null)
      setCaption('')
      try {
        const consent = await api.consent()
        if (!consent.switches.some((s) => s.id === 'microphone' && s.granted)) {
          setState('consent')
          return
        }
        const tone = consent.switches.some((x) => x.id === 'voice_tone' && x.granted)
        turn.current = await listenWithTone(
          engine,
          setCaption,
          tone,
          handsFree ? () => void end() : undefined,
        )
        setState('listening')
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        setState('idle')
      }
    },
    [engine, end],
  )

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

  // What was heard stays up for a moment after it is sent; the reply carries on in the thread.
  useEffect(() => {
    if (state !== 'idle' || !caption) return
    const t = setTimeout(() => {
      setCaption('')
    }, 6000)
    return () => {
      clearTimeout(t)
    }
  }, [state, caption])

  // The wake word only runs when it is set up and the microphone switch is on.
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])
  useEffect(() => {
    const setup = wakeSetup()
    if (!setup) return
    let stop: (() => void) | null = null
    let gone = false
    api
      .consent()
      .then(async (consent) => {
        if (!consent.switches.some((s) => s.id === 'microphone' && s.granted)) return
        const stopWake = await startWake(setup, () => {
          if (stateRef.current === 'idle') void begin(true)
        })
        if (gone) stopWake()
        else {
          stop = stopWake
          setWake('on')
        }
      })
      .catch(() => {
        if (!gone) setWake('failed')
      })
    return () => {
      gone = true
      stop?.()
    }
  }, [begin])

  const label =
    state === 'listening'
      ? 'Listening. Tap to send'
      : state === 'transcribing'
        ? 'Working out what you said'
        : wake === 'on'
          ? `Say "${WAKE_LABEL}" or tap to talk (Alt+V)`
          : 'Tap to talk (Alt+V)'

  return (
    <div className="mic" data-testid="voice">
      <button
        type="button"
        className={`orb orb--${state}`}
        aria-label={label}
        title={label}
        aria-pressed={state === 'listening'}
        disabled={state === 'transcribing' || state === 'consent'}
        onClick={toggle}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="9" y="3" width="6" height="12" rx="3" />
          <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3" fill="none" />
        </svg>
      </button>
      <div
        className="mic__pop"
        hidden={
          !caption && !error && state !== 'consent' && wake !== 'failed' && state !== 'listening'
        }
      >
        {state === 'listening' && <p className="eyebrow">Listening</p>}
        <p className="orb__caption" aria-live="polite" data-testid="voice-caption">
          {caption}
        </p>
        {state === 'consent' && (
          <div className="confirm" role="dialog" aria-label="Turn on the microphone">
            <p>
              To listen, Lodestar needs the microphone switch.{' '}
              {engine === 'browser'
                ? "Your browser's speech recognition may send the audio to its maker."
                : engine === 'device'
                  ? 'Speech is turned into text on this device; the audio never leaves it.'
                  : 'Speech is turned into text on this server, and the audio is not kept.'}
            </p>
            <div className="actions">
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
        {wake === 'failed' && (
          <p className="muted small" data-testid="wake-off">
            The wake word couldn&apos;t start; check it in Settings. Tap to talk still works.
          </p>
        )}
        {error && <p role="alert">{error}</p>}
      </div>
    </div>
  )
}
