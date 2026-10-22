import { useState } from 'react'

import { Orb } from '../voice/Orb'
import type { useSession } from './useSession'

/** Things people often say, one tap away. Each is sent as if typed. */
const STARTERS = [
  'Something quick',
  'When am I sharpest?',
  'How am I doing this week?',
  'Make me a game where I remember a phone number while doing maths',
]

/** Where you talk to Najma: type or tap the microphone, with a few starters. Hidden while a game
 * is running so keys go to the game. */
export function Composer({
  session,
  onVoice,
}: {
  session: ReturnType<typeof useSession>
  onVoice: (text: string) => void
}) {
  const { state, send, nextGame } = session
  const [text, setText] = useState('')
  const waiting = state.busy || state.phase === 'starting'
  const canPlay = state.phase === 'chatting' && !state.confirm && !state.busy
  const quiet = state.feed.length === 0 && state.phase === 'home'
  const chips = (canPlay || quiet) && (
    <div className="composer__chips">
      {canPlay && (
        <button type="button" className="chip chip--strong" onClick={() => void nextGame()}>
          Play a game
        </button>
      )}
      {quiet &&
        STARTERS.map((s) => (
          <button
            key={s}
            type="button"
            className="chip"
            onClick={() => {
              void send(s)
            }}
          >
            {s.length > 34 ? 'Make me a game' : s}
          </button>
        ))}
    </div>
  )
  return (
    <div className={`composer${quiet ? ' composer--home' : ''}`}>
      {!quiet && chips}
      <form
        className="composer__box"
        onSubmit={(e) => {
          e.preventDefault()
          const said = text
          setText('')
          if (said.trim()) void send(said)
        }}
      >
        <label className="sr-only" htmlFor="say">
          Say something to Najma
        </label>
        <input
          id="say"
          data-testid="say"
          value={text}
          maxLength={2000}
          autoComplete="off"
          placeholder={quiet ? 'Tell Najma how your day is going' : 'Reply to Najma'}
          onChange={(e) => {
            setText(e.target.value)
          }}
        />
        <div className="composer__tools">
          <Orb onTranscript={onVoice} />
          <button
            type="submit"
            className="send"
            aria-label="Send"
            title="Send"
            disabled={!text.trim() || waiting}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </form>
      {quiet && chips}
    </div>
  )
}
