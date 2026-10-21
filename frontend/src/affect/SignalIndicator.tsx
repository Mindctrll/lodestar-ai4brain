import { useSyncExternalStore } from 'react'

import { api } from '../api/client'
import { activeSignals, stopSignal, subscribe, type CueSignal } from './cues'

const TEXT: Record<CueSignal, { label: string; switchId: string }> = {
  camera: { label: 'Camera signal in use', switchId: 'camera' },
  voice: { label: 'Voice signal in use', switchId: 'voice_tone' },
}

/** Always on screen while a camera or voice signal is in use (docs/plan/12, rule 6), with a
 * one-tap way to turn it off. */
export function SignalIndicator() {
  const signals = useSyncExternalStore(subscribe, activeSignals)
  if (signals.length === 0) return null
  return (
    <div className="signal-indicator" role="status" data-testid="signal-indicator">
      {signals.map((s) => (
        <span key={s} className="signal-indicator__item">
          <span aria-hidden="true" className="signal-indicator__dot" />
          {TEXT[s].label}
          <button
            type="button"
            onClick={() => {
              stopSignal(s)
              void api.setConsent(TEXT[s].switchId, false).catch(() => undefined)
            }}
          >
            Turn off
          </button>
        </span>
      ))}
    </div>
  )
}
