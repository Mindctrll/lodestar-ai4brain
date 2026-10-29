import { useState } from 'react'

import { endDemo, inDemo, startDemo } from '../api/client'

/** One switch between this browser's own data and Alex, a demo person with four months of
 * practice. Switching reloads the page so every panel shows the right person. */
export function DemoToggle({ variant }: { variant: 'rail' | 'welcome' }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const on = inDemo()

  const toggle = async () => {
    setBusy(true)
    setError(null)
    try {
      if (on) endDemo()
      else await startDemo()
      window.location.reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  if (variant === 'welcome') {
    return (
      <>
        <button type="button" className="ghost" disabled={busy} onClick={() => void toggle()}>
          {busy ? 'Opening the demo…' : 'Look around as Alex, a demo person'}
        </button>
        {error && <p role="alert">{error}</p>}
      </>
    )
  }
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      className="rail__item demo-toggle"
      aria-label="Demo person"
      title={
        error ??
        (on ? 'Showing Alex, a demo person. Switch off for your own data.' : 'Show a demo person')
      }
      disabled={busy}
      onClick={() => void toggle()}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM19 8v6M22 11h-6" />
      </svg>
      <span className="rail__label">{on ? 'Demo: Alex' : 'Demo person'}</span>
      <span className="demo-toggle__track" aria-hidden="true" />
    </button>
  )
}
