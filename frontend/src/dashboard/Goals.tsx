import { useState } from 'react'

import type { GoalView } from '../api/types'

/** A wide start: Lodestar's first range is about ±50 points. */
const START = 50
const DAY = 86_400_000
const round = (x: number) => String(Math.round(x))

/** Goal tracking (docs/plan/13, chart 4): a goal is "know this skill to within ±N points". Each
 * card shows how far the range has narrowed (the ring), the range now against the target width
 * on a 0-100 scale, and the time and rounds left. Never a bare score. */
export function Goals({ goals, testId = 'goals' }: { goals: GoalView[]; testId?: string }) {
  const [now0] = useState(() => Date.now())
  if (goals.length === 0)
    return (
      <p className="muted">
        No goal yet. Tell Lodestar something like &ldquo;I want my memory solid before exams&rdquo;.
      </p>
    )
  return (
    <ul className="goals" data-testid={testId}>
      {goals.map((g) => {
        const now = g.range_now
        const done = now === null ? 0 : Math.min(1, Math.max(0, (START - now) / (START - g.target)))
        const pctDone = Math.round(done * 100)
        const days = Math.max(0, Math.ceil((new Date(`${g.due}T23:59:59`).getTime() - now0) / DAY))
        const due = new Date(`${g.due}T00:00:00`).toLocaleDateString('en-GB', {
          day: 'numeric',
          month: 'short',
        })
        const mid = g.low !== null && g.high !== null ? (g.low + g.high) / 2 : 50
        const ring = 2 * Math.PI * 30
        return (
          <li key={g.goal_id} className={`goal${g.met ? ' goal--met' : ''}`}>
            <div className="goal__top">
              <div>
                <p className="goal__skill">{g.name}</p>
                <p className="goal__aim">Pin it down to ±{round(g.target)} points</p>
              </div>
              <span className={`goal__status${g.met ? ' goal__status--met' : ''}`}>
                {g.met ? 'Reached' : 'In progress'}
              </span>
            </div>
            <div className="goal__body">
              <svg
                className="goal__ring"
                viewBox="0 0 72 72"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pctDone}
                aria-label={`${g.name} goal progress`}
              >
                <circle cx="36" cy="36" r="30" className="goal__ring-track" />
                <circle
                  cx="36"
                  cy="36"
                  r="30"
                  className="goal__ring-fill"
                  strokeDasharray={`${String(ring * done)} ${String(ring)}`}
                  transform="rotate(-90 36 36)"
                />
                <text x="36" y="36" dy="0.35em" className="goal__ring-text">
                  {pctDone}%
                </text>
              </svg>
              <div className="goal__numbers">
                <p>
                  <strong>{now === null ? '–' : `±${round(now)}`}</strong>
                  <span className="muted"> now</span>
                </p>
                <p>
                  <strong>±{round(g.target)}</strong>
                  <span className="muted"> aim</span>
                </p>
              </div>
            </div>
            {now !== null && g.low !== null && g.high !== null && (
              <div className="goal__scale" aria-hidden="true">
                <span
                  className="goal__band"
                  style={{ left: `${String(g.low)}%`, width: `${String(g.high - g.low)}%` }}
                />
                <span
                  className="goal__target"
                  style={{
                    left: `${String(Math.max(0, mid - g.target))}%`,
                    width: `${String(Math.min(100, 2 * g.target))}%`,
                  }}
                />
                <span className="goal__mid" style={{ left: `${String(mid)}%` }} />
              </div>
            )}
            <p className="goal__note">
              {now === null
                ? 'Not measured yet.'
                : `Likely ${round(g.low ?? 0)}-${round(g.high ?? 0)}% now; the dashed box is the aim.`}
            </p>
            <p className="goal__foot">
              <span>
                by {due} · {days} {days === 1 ? 'day' : 'days'} left
              </span>
              {!g.met && g.rounds_left !== null && <span>about {g.rounds_left} more rounds</span>}
            </p>
          </li>
        )
      })}
    </ul>
  )
}
