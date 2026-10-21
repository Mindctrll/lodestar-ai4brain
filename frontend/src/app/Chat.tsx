import { useState } from 'react'

import { Cited } from './Cited'
import type { SessionState } from './useSession'

/** Talking to Najma between games: questions, goals, how the day is going (docs/plan/03,
 * converse). A change Najma wants to make shows as a question with Yes and No. */
export function Chat({
  state,
  send,
  answer,
  nextGame,
  onWhy,
}: {
  state: SessionState
  send: (text: string) => Promise<void>
  answer: (confirmed: boolean) => Promise<void>
  nextGame: () => Promise<void>
  onWhy: (decisionId: string) => void
}) {
  const [text, setText] = useState('')
  const waiting = state.busy || state.phase === 'starting'
  return (
    <section className="card chat" data-testid="chat" aria-label="Talk to Najma">
      {state.chat.length > 0 && (
        <ol className="chat__lines" aria-live="polite">
          {state.chat.map((line, i) => (
            <li key={i} className={`chat__line chat__line--${line.who}`}>
              <Cited text={line.text} refs={line.refs} onWhy={onWhy} />
            </li>
          ))}
        </ol>
      )}
      {waiting && state.chat.length > 0 && <p className="muted">Najma is thinking…</p>}
      {state.confirm && (
        <div className="confirm" role="dialog" aria-label="Najma asks" data-testid="confirm">
          <p>
            <Cited text={state.confirm.prompt} />
          </p>
          <div className="flex gap-2">
            <button type="button" className="primary" onClick={() => void answer(true)}>
              Yes
            </button>
            <button type="button" onClick={() => void answer(false)}>
              No
            </button>
          </div>
        </div>
      )}
      {state.phase === 'chatting' && !state.confirm && !state.busy && (
        <button type="button" className="primary" onClick={() => void nextGame()}>
          Play a game
        </button>
      )}
      <form
        className="chat__form"
        onSubmit={(e) => {
          e.preventDefault()
          const said = text
          setText('')
          void send(said)
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
          placeholder="Ask why, set a goal, or tell me how your day is going"
          onChange={(e) => {
            setText(e.target.value)
          }}
        />
        <button type="submit" disabled={!text.trim() || waiting}>
          Send
        </button>
      </form>
    </section>
  )
}
