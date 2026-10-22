import type { GoalView } from '../api/types'

/** Goal tracking (docs/plan/13, chart 4): how far the range has narrowed toward the target,
 * not only the score. */
export function Goals({ goals, testId = 'goals' }: { goals: GoalView[]; testId?: string }) {
  if (goals.length === 0)
    return (
      <p className="muted">
        No goal yet. Tell Najma something like &ldquo;I want my memory solid before exams&rdquo;.
      </p>
    )
  return (
    <ul className="goals" data-testid={testId}>
      {goals.map((g) => {
        const now = g.range_now
        // Progress from a wide start (±50) toward the target width.
        const done = now === null ? 0 : Math.min(1, Math.max(0, (50 - now) / (50 - g.target)))
        return (
          <li key={g.goal_id} className="goal">
            <div className="goal__head">
              <strong>{g.name}</strong>
              <span className="muted">
                by{' '}
                {new Date(`${g.due}T00:00:00`).toLocaleDateString('en-GB', {
                  day: 'numeric',
                  month: 'short',
                })}
              </span>
            </div>
            <div
              className="goal__bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(done * 100)}
              aria-label={`${g.name} goal progress`}
            >
              <span style={{ width: `${String(Math.round(done * 100))}%` }} />
            </div>
            <p className="muted">
              {now === null
                ? `Aim: range within ±${String(g.target)} points. Not measured yet.`
                : g.met
                  ? `Range now ±${String(Math.round(now))} points (${String(Math.round(g.low ?? 0))}-${String(Math.round(g.high ?? 0))}%): goal reached.`
                  : `Range now ±${String(Math.round(now))} points (${String(Math.round(g.low ?? 0))}-${String(Math.round(g.high ?? 0))}%), aim ±${String(g.target)}${g.rounds_left ? `, about ${String(g.rounds_left)} more rounds` : ''}.`}
            </p>
          </li>
        )
      })}
    </ul>
  )
}
