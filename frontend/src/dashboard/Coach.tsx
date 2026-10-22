import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Persona } from '../api/types'
import { Glyph } from '../app/icons'
import { PERSONAS } from '../app/personas'

/** The four coaches (docs/plan/09, personas; UW20). They say the same facts in their own voice;
 * switching takes effect from the next reply. */
export function Coach({ onChange }: { onChange?: (persona: Persona) => void }) {
  const [current, setCurrent] = useState<Persona | null>(null)
  const [saving, setSaving] = useState<Persona | null>(null)
  useEffect(() => {
    api.me().then(
      (me) => {
        setCurrent(me.persona as Persona)
      },
      () => undefined,
    )
  }, [])

  const pick = (id: Persona) => {
    setSaving(id)
    api.setPersona(id).then(
      () => {
        setCurrent(id)
        setSaving(null)
        onChange?.(id)
      },
      () => {
        setSaving(null)
      },
    )
  }

  return (
    <div className="stack" data-testid="coach-page">
      <ul className="coaches-grid">
        {PERSONAS.map((p) => {
          const look = p
          const mine = current === p.id
          return (
            <li key={p.id} className={`coach-card${mine ? ' coach-card--mine' : ''}`}>
              <div className="coach-card__top">
                <span
                  className="coach-card__face"
                  style={{ background: look.soft, color: look.strong }}
                  aria-hidden="true"
                >
                  <Glyph name={look.icon} />
                </span>
                <div>
                  <h2>{p.name}</h2>
                  <p className="muted">{p.style}</p>
                </div>
                {mine && <span className="coach-card__badge">Your coach</span>}
              </div>
              <p className="coach-card__line" style={{ borderColor: look.strong }}>
                &ldquo;{p.sample}&rdquo;
              </p>
              <button
                type="button"
                className={mine ? 'small' : 'primary small'}
                disabled={mine || saving !== null}
                onClick={() => {
                  pick(p.id)
                }}
              >
                {mine ? 'Coaching you now' : saving === p.id ? 'Switching…' : `Choose ${p.name}`}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
