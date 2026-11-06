import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { AgentCard, PlateauView, SplitView, WhyLine, WidenedRange } from '../api/types'

/** What each stress case looks like on screen. Each has its own colour, so it can't be mistaken
 * for another: red for a rushed round, amber for a plateau, blue for "why", violet for pushback,
 * teal for a forecast, green and orange for a split profile's two tracks. */

export function WhyLines({ lines }: { lines: WhyLine[] }) {
  if (lines.length === 0) return null
  return (
    <ul className="why-lines" data-testid="why-lines">
      {lines.map((line) => (
        <li key={line.source}>
          <span className="why-lines__source">{line.source}</span>
          {line.text}
        </li>
      ))}
    </ul>
  )
}

const TRACK: Record<string, { label: string; tone: string }> = {
  advanced: { label: 'Advanced track', tone: 'advanced' },
  foundation: { label: 'Foundation track', tone: 'foundation' },
  new_format: { label: 'New format', tone: 'plateau' },
}

export function TrackTag({ track, level }: { track: string; level: number }) {
  const shown = TRACK[track]
  if (!shown) return null
  return (
    <span className={`stress-tag stress-tag--${shown.tone}`} data-testid="track-tag">
      {shown.label}
      {track !== 'new_format' && ` · level ${String(Math.max(1, Math.round(level * 10)))}/10`}
    </span>
  )
}

/** Two ranges on one 0-100 track: what it was, what it is now. */
function RangeChange({ item }: { item: WidenedRange }) {
  return (
    <li className="range-change">
      <p>
        <strong>{item.name}</strong>{' '}
        <span className="muted">
          stays at {item.value}%, range {item.before_low}-{item.before_high}% →{' '}
          <strong>
            {item.after_low}-{item.after_high}%
          </strong>
        </span>
      </p>
      <div className="range-change__track" aria-hidden="true">
        <span
          className="range-change__after"
          style={{
            left: `${String(item.after_low)}%`,
            width: `${String(item.after_high - item.after_low)}%`,
          }}
        />
        <span
          className="range-change__before"
          style={{
            left: `${String(item.before_low)}%`,
            width: `${String(item.before_high - item.before_low)}%`,
          }}
        />
        <span className="range-change__dot" style={{ left: `${String(item.value)}%` }} />
      </div>
    </li>
  )
}

const ANSWERS = [
  ['rushing', 'I was rushing'],
  ['distracted', 'I got distracted'],
  ['testing', 'I was just trying it out'],
] as const

/** The button masher: a full red screen as soon as the round ends. It didn't count, the estimate
 * didn't drop, and Lodestar asks what happened instead of assuming. */
export function RushedScreen({
  card,
  sessionId,
  onClose,
}: {
  card: Extract<AgentCard, { card: 'rushed' }>
  sessionId: string | null
  onClose: () => void
}) {
  const [answer, setAnswer] = useState<string | null>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose])
  const reply = (value: string) => {
    setAnswer(value)
    if (sessionId)
      void api
        .label({ session_id: sessionId, kind: 'rushed', value, round_id: card.round_id })
        .catch(() => undefined)
  }
  return (
    <div className="rushed" role="alertdialog" aria-label="Round not counted" data-testid="rushed">
      <div className="rushed__body">
        <p className="rushed__flag">Round flagged · {card.game}</p>
        <h2>That round didn&apos;t count</h2>
        <p className="rushed__lede">
          Those answers came too fast to tell me anything about you, so I&apos;m not treating it as
          a drop in skill.
        </p>
        <ul className="rushed__stats">
          {card.median_rt_ms !== null && (
            <li>
              <strong>{card.median_rt_ms} ms</strong>
              <span>typical answer</span>
            </li>
          )}
          {card.answered > 0 && (
            <li>
              <strong>
                {card.correct}/{card.answered}
              </strong>
              <span>right</span>
            </li>
          )}
          <li>
            <strong>0</strong>
            <span>points of change to your estimate</span>
          </li>
        </ul>
        {card.dims.length > 0 && (
          <>
            <p className="rushed__note">Instead, I&apos;m less sure about you for now:</p>
            <ul className="rushed__ranges">
              {card.dims.map((d) => (
                <RangeChange key={d.name} item={d} />
              ))}
            </ul>
          </>
        )}
        {answer === null ? (
          <>
            <p className="rushed__ask">What happened?</p>
            <div className="rushed__actions">
              {ANSWERS.map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => {
                    reply(value)
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            <p className="rushed__ask">Thanks, noted. Take a breath; the next one can count.</p>
            <div className="rushed__actions">
              <button type="button" onClick={onClose} autoFocus data-testid="rushed-close">
                Back to Lodestar
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/** The plateau, as a popup on the conversation. Dismissed for this browser tab. */
export function PlateauToast({
  plateau,
  onTry,
  onSee,
}: {
  plateau: PlateauView
  onTry: (p: PlateauView) => void
  onSee: (p: PlateauView) => void
}) {
  const [closed, setClosed] = useState(false)
  if (closed) return null
  return (
    <aside className="toast stress stress--plateau" role="status" data-testid="plateau-toast">
      <p className="stress-tag stress-tag--plateau">Plateau spotted</p>
      <p>
        <strong>{plateau.name}</strong> has stayed near {Math.round(plateau.percent)}% (likely{' '}
        {Math.round(plateau.low)}-{Math.round(plateau.high)}%) for {plateau.days} days of practice.
      </p>
      {plateau.game_name && (
        <p className="muted small">Next, try a new format: {plateau.game_name}.</p>
      )}
      <div className="actions">
        <button
          type="button"
          className="primary"
          onClick={() => {
            onTry(plateau)
          }}
        >
          Try a new format
        </button>
        <button
          type="button"
          onClick={() => {
            onSee(plateau)
          }}
        >
          See the curve
        </button>
        <button
          type="button"
          className="ghost"
          aria-label="Dismiss"
          onClick={() => {
            setClosed(true)
          }}
        >
          Not now
        </button>
      </div>
    </aside>
  )
}

/** The same plateau on the skill's own page, with the change of approach. */
export function PlateauNote({
  plateau,
  onTry,
}: {
  plateau: PlateauView
  onTry?: ((p: PlateauView) => void) | undefined
}) {
  return (
    <div className="stress stress--plateau" data-testid="plateau-note">
      <p className="stress-tag stress-tag--plateau">Plateau · {plateau.days} days</p>
      <p>
        Your estimate has stayed near {Math.round(plateau.percent)}% (likely{' '}
        {Math.round(plateau.low)}-{Math.round(plateau.high)}%) over {plateau.answers} answers. More
        of the same probably won&apos;t move it, so I&apos;ll change things.
      </p>
      {plateau.game_name && (
        <p>
          <strong>New format:</strong> {plateau.game_name}
          {plateau.same_skill ? '.' : ', from the same family of skills.'}
        </p>
      )}
      <p>
        <strong>New approach:</strong> {plateau.strategy}
      </p>
      {onTry && (
        <button
          type="button"
          className="primary"
          onClick={() => {
            onTry(plateau)
          }}
        >
          Try a new format
        </button>
      )}
    </div>
  )
}

/** A split profile: two tracks, each at its own level, never one average difficulty. */
export function SplitPlan({ split, onPlay }: { split: SplitView; onPlay: () => void }) {
  const sides = [split.advanced, split.foundation]
  return (
    <div className="stress stress--split" data-testid="split-plan">
      <p className="stress-tag stress-tag--split">
        Split profile · {Math.round(split.gap)} points apart
      </p>
      <p>
        These two skills are far apart, so I don&apos;t use one difficulty for both. Rounds take
        turns between two tracks.
      </p>
      <div className="split-tracks">
        {sides.map((side) => (
          <article
            key={side.dim}
            className={`split-track split-track--${side.track}`}
            data-track={side.track}
          >
            <p className="split-track__kind">
              {side.track === 'advanced' ? '▲ Advanced track' : '▼ Foundation track'}
            </p>
            <h4>{side.name}</h4>
            <p className="muted small">
              {Math.round(side.percent)}%, likely {Math.round(side.low)}-{Math.round(side.high)}%
            </p>
            <div className="range-bar" aria-hidden="true">
              <span
                className="range-bar__band"
                style={{
                  left: `${String(side.low)}%`,
                  width: `${String(side.high - side.low)}%`,
                }}
              />
              <span className="range-bar__dot" style={{ left: `${String(side.percent)}%` }} />
            </div>
            <p>
              <strong>Level {Math.max(1, Math.round(side.level * 10))} of 10</strong>, aiming for{' '}
              {Math.round(side.target_p * 100)}% right
            </p>
            {side.game_name && <p className="muted small">Next up: {side.game_name}</p>}
          </article>
        ))}
      </div>
      <button type="button" className="primary" onClick={onPlay}>
        Play this plan
      </button>
    </div>
  )
}

/** The cards the agent adds to the conversation. */
export function AgentCardView({
  card,
  onWhy,
}: {
  card: Exclude<AgentCard, { card: 'rushed' }>
  onWhy: (decisionId: string) => void
}) {
  switch (card.card) {
    case 'why':
      return (
        <article className="turn-card stress stress--why" data-testid="why-card-inline">
          <p className="stress-tag stress-tag--why">The data behind my pick · {card.when}</p>
          {card.lines.length === 0 && <p>{card.reason}</p>}
          <WhyLines lines={card.lines} />
          <button
            type="button"
            className="link"
            onClick={() => {
              onWhy(card.decision_id)
            }}
          >
            See every option I weighed
          </button>
        </article>
      )
    case 'history':
      return (
        <article className="turn-card stress stress--why" data-testid="history-card">
          <p className="stress-tag stress-tag--why">Your history</p>
          <table className="history-table">
            <tbody>
              {card.rows.map((r, i) => (
                <tr key={i}>
                  <td className="muted">{r.day}</td>
                  <td>{r.game}</td>
                  <td>{r.score === null ? 'not counted' : `${String(r.score)}% right`}</td>
                  <td>
                    {r.decision_id && (
                      <button
                        type="button"
                        className="link"
                        onClick={() => {
                          if (r.decision_id) onWhy(r.decision_id)
                        }}
                      >
                        Why?
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
      )
    case 'forecast':
      return (
        <article className="turn-card stress stress--forecast" data-testid="forecast-card">
          <p className="stress-tag stress-tag--forecast">A range, not a promise</p>
          <p className="muted small">
            If you keep your current pace ({card.sessions} more sessions). No single number: every
            forecast is an 80% range.
          </p>
          <ul className="forecast-rows">
            {card.rows.map((r) => (
              <li key={r.name}>
                <p>
                  <strong>{r.name}</strong>{' '}
                  <span className="muted">
                    likely {r.low}-{r.high}%
                  </span>
                </p>
                <div className="forecast-rows__track" aria-hidden="true">
                  <span
                    className="forecast-rows__now"
                    style={{
                      left: `${String(r.now_low)}%`,
                      width: `${String(r.now_high - r.now_low)}%`,
                    }}
                  />
                  <span
                    className="forecast-rows__then"
                    style={{ left: `${String(r.low)}%`, width: `${String(r.high - r.low)}%` }}
                  />
                </div>
                <p className="muted small">
                  Today {r.now_low}-{r.now_high}%
                </p>
              </li>
            ))}
          </ul>
          {card.held !== null && (
            <p className="muted small">
              Ranges like these held {card.held}% of the time on real players the model never saw.
            </p>
          )}
        </article>
      )
    case 'pushback':
      return (
        <article className="turn-card stress stress--pushback" data-testid="pushback-card">
          <p className="stress-tag stress-tag--pushback">Pushback accepted · {card.game}</p>
          <ul className="rushed__ranges">
            {card.dims.map((d) => (
              <RangeChange key={d.name} item={d} />
            ))}
          </ul>
          {card.acs_after !== null && (
            <p>
              <strong>AI Collaboration Score</strong>{' '}
              {card.acs_before !== null && <span className="muted">{card.acs_before} → </span>}
              <strong>{card.acs_after}</strong>{' '}
              <span className="muted">
                (likely {card.acs_low}-{card.acs_high}). Critical verification and iteration both
                went up.
              </span>
            </p>
          )}
        </article>
      )
  }
}
