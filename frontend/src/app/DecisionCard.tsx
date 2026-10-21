import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Decision } from '../api/types'

const PART_NAMES: Record<string, string> = {
  uncertainty: 'how unsure I am',
  staleness: 'time since you practised',
  goal_weight: 'your goal',
  plan_priority: 'plan',
  bandit_gain: 'expected gain',
  fatigue_penalty: 'tiredness',
  repetition: 'played just now',
}

/** The "why" card behind a decision: the question, the reason and the top candidates with the
 * parts of their score (docs/plan/03, How plan_next decides). */
export function DecisionCard({
  decisionId,
  name,
  onClose,
}: {
  decisionId: string
  name: (option: string) => string
  onClose: () => void
}) {
  const [decision, setDecision] = useState<Decision | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    api.decision(decisionId).then(setDecision, () => {
      setFailed(true)
    })
  }, [decisionId])

  return (
    <section className="card why" role="dialog" aria-label="Why this choice" data-testid="why-card">
      <h2>Why this choice</h2>
      {failed && <p role="alert">I couldn&apos;t load that choice.</p>}
      {decision && (
        <>
          <p>{decision.reason}</p>
          {decision.candidates.length > 0 && (
            <>
              <p className="muted">{decision.question} Top options:</p>
              <ol className="why__options">
                {decision.candidates.slice(0, 3).map((c) => (
                  <li key={c.option}>
                    <strong>{name(c.option)}</strong> <span>score {c.score.toFixed(2)}</span>
                    <ul className="why__parts">
                      {Object.entries(c.breakdown ?? {})
                        .filter(([, v]) => Math.abs(v) > 1e-9)
                        .map(([k, v]) => (
                          <li key={k}>
                            {PART_NAMES[k] ?? k}: {v.toFixed(2)}
                          </li>
                        ))}
                    </ul>
                  </li>
                ))}
              </ol>
            </>
          )}
        </>
      )}
      <button type="button" onClick={onClose}>
        Close
      </button>
    </section>
  )
}
