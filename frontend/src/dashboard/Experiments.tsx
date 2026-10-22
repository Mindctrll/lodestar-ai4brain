import { useCallback, useEffect, useState } from 'react'

import { api } from '../api/client'
import type { ExperimentView } from '../api/types'
import { Cited } from '../app/Cited'

/** Personal experiments (docs/plan/09, 13; UW10): the plan, progress dots per condition, and the
 * result card with how sure it is. Inconclusive results say so. */
export function Experiments({ onAsk }: { onAsk: () => void }) {
  const [list, setList] = useState<ExperimentView[] | null>(null)
  const load = useCallback(() => {
    api.experiments().then(setList, () => {
      setList([])
    })
  }, [])
  useEffect(load, [load])

  if (list === null) return <p className="muted">Loading…</p>
  if (list.length === 0)
    return (
      <section className="card" data-testid="experiments">
        <h2>No experiments yet</h2>
        <p>
          Lodestar can test whether you do better in the morning or the evening: a few sessions at
          each time, with the same games.
        </p>
        <button type="button" className="primary" onClick={onAsk}>
          Start one
        </button>
      </section>
    )
  return (
    <div data-testid="experiments">
      {list.map((e) => (
        <section key={e.exp_id} className="card experiment">
          <h2>{e.hypothesis}</h2>
          <p className="muted small">
            {e.status === 'running'
              ? 'Running'
              : e.status === 'inconclusive'
                ? 'Inconclusive'
                : 'Done'}{' '}
            · games: {e.games.join(', ')}
          </p>
          <ul className="experiment__progress">
            {Object.entries(e.progress).map(([condition, done]) => (
              <li key={condition}>
                <span className="experiment__label">{condition}</span>
                {Array.from({ length: e.sessions_per_condition }, (_, i) => (
                  <span
                    key={i}
                    className={`dot${i < done ? ' dot--done' : ''}`}
                    aria-hidden="true"
                  />
                ))}
                <span className="muted small">
                  {done} of {e.sessions_per_condition}
                </span>
              </li>
            ))}
          </ul>
          {e.summary && (
            <p className="experiment__result" data-testid="experiment-result">
              <Cited text={e.summary} />
            </p>
          )}
          {e.status === 'running' && (
            <button
              type="button"
              onClick={() => {
                void api.cancelExperiment(e.exp_id).then(load)
              }}
            >
              Stop this experiment
            </button>
          )}
        </section>
      ))}
    </div>
  )
}
