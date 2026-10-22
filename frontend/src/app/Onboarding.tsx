import { useEffect, useState } from 'react'

import { api, signUp } from '../api/client'
import type { Persona, Registry } from '../api/types'
import { PERSONAS } from './personas'

type Notice = Registry['consent']

type Step = 'welcome' | 'age' | 'under' | 'consent' | 'coach'

/** First visit (UW1): what Lodestar is, the age check, consent in plain words, and a coach. Nothing
 * is stored until the last step; the camera is never touched here. */
export function Onboarding({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState<Step>('welcome')
  const [notice, setNotice] = useState<Notice | null>(null)
  const [consent, setConsent] = useState<Record<string, boolean>>({})
  const [persona, setPersona] = useState<Persona>('willow')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.registry().then(
      (registry) => {
        setNotice(registry.consent)
        setConsent(Object.fromEntries(registry.consent.switches.map((s) => [s.id, s.default])))
      },
      () => {
        setError("Couldn't reach Lodestar. Try again in a moment.")
      },
    )
  }, [])

  const finish = async () => {
    setSaving(true)
    setError(null)
    try {
      await signUp({ consent, persona })
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaving(false)
    }
  }

  return (
    <section className="card onboarding" data-testid="onboarding">
      {step === 'welcome' && (
        <>
          <h2>Welcome to Lodestar</h2>
          <p>
            Lodestar picks short games that train how you focus, remember and reason, and explains
            every choice it makes.
          </p>
          <p className="muted">
            Lodestar is a practice coach. It doesn&apos;t assess medical or psychological
            conditions.
          </p>
          <button
            type="button"
            className="primary"
            onClick={() => {
              setStep('age')
            }}
          >
            Get started
          </button>
        </>
      )}

      {step === 'age' && (
        <>
          <h2>How old are you?</h2>
          <p>This prototype is for people aged {notice?.age_minimum ?? 18} and over.</p>
          <div className="flex gap-2">
            <button
              type="button"
              className="primary"
              onClick={() => {
                setStep('consent')
              }}
            >
              I&apos;m {notice?.age_minimum ?? 18} or older
            </button>
            <button
              type="button"
              onClick={() => {
                setStep('under')
              }}
            >
              I&apos;m younger
            </button>
          </div>
        </>
      )}

      {step === 'under' && (
        <>
          <h2>Not yet, sorry</h2>
          <p>
            Lodestar needs a parent or guardian&apos;s consent for younger people, and this
            prototype can&apos;t ask for it yet. Nothing about you has been stored.
          </p>
        </>
      )}

      {step === 'consent' && notice && (
        <>
          <h2>What Lodestar may do</h2>
          <p className="muted">You can change any of these later in Settings.</p>
          <ul className="switches">
            {notice.switches.map((s) => (
              <li key={s.id}>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={consent[s.id] ?? false}
                    disabled={s.required}
                    onChange={(e) => {
                      setConsent((c) => ({ ...c, [s.id]: e.target.checked }))
                    }}
                  />
                  <span>
                    <strong>{s.title}</strong>
                    {s.required && <span className="muted"> (needed)</span>}
                    <br />
                    <span className="muted">{s.plain}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="primary"
            onClick={() => {
              setStep('coach')
            }}
          >
            Continue
          </button>
        </>
      )}

      {step === 'coach' && (
        <>
          <h2>Pick a coach</h2>
          <p className="muted">They all say the same facts, in their own way.</p>
          <div className="coaches" role="radiogroup" aria-label="Coach">
            {PERSONAS.map((p) => (
              <label key={p.id} className="coach-option">
                <input
                  type="radio"
                  name="coach"
                  value={p.id}
                  checked={persona === p.id}
                  onChange={() => {
                    setPersona(p.id)
                  }}
                />
                <span>
                  <strong>{p.name}</strong> · {p.style}
                  <br />
                  <span className="muted">&ldquo;{p.sample}&rdquo;</span>
                </span>
              </label>
            ))}
          </div>
          <button type="button" className="primary" disabled={saving} onClick={() => void finish()}>
            Let&apos;s start
          </button>
        </>
      )}

      {error && <p role="alert">{error}</p>}
    </section>
  )
}
