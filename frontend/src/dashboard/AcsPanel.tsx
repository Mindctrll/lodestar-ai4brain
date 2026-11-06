import type { AcsView } from '../api/types'
import { AcsGauge } from './charts'

const TIPS: Record<string, string> = {
  V: 'Check the AI’s steps before you accept them.',
  A: 'Try a step yourself before asking for a hint.',
  I: 'After a miss, change something and try again.',
  C: 'Say how sure you are, then see if you were right.',
  R: 'Take the breaks Lodestar suggests.',
}

/** The AI Collaboration Score (docs/plan/11): a gauge with its range, and each part with its own
 * range. Parts with too few moments say so instead of guessing. */
export function AcsPanel({ acs }: { acs: AcsView }) {
  return (
    <div className="acs" data-testid="acs">
      <AcsGauge acs={acs} />
      {acs.pushbacks > 0 && (
        <p className="stress stress--pushback acs__pushback" data-testid="acs-pushback">
          <strong>
            You pushed back {acs.pushbacks} time{acs.pushbacks === 1 ? '' : 's'}.
          </strong>{' '}
          Questioning a result counts toward critical verification and iteration.
        </p>
      )}
      <ul className="acs__parts">
        {acs.components.map((c) => (
          <li key={c.code}>
            <div className="acs__row">
              <strong>{c.name}</strong>
              <span className="muted">
                {c.enough_data
                  ? `${String(Math.round(c.score * 100))} (${String(Math.round(c.low * 100))}-${String(Math.round(c.high * 100))}), from ${String(c.opportunities)} moments`
                  : `not enough moments yet (${String(c.opportunities)})`}
              </span>
            </div>
            <div className="range-bar" aria-hidden="true">
              <span
                className="range-bar__band"
                style={{
                  left: `${String(c.low * 100)}%`,
                  width: `${String((c.high - c.low) * 100)}%`,
                }}
              />
              {c.enough_data && (
                <span className="range-bar__dot" style={{ left: `${String(c.score * 100)}%` }} />
              )}
            </div>
            <p className="muted small">{TIPS[c.code] ?? ''}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
