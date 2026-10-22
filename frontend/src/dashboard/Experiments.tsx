import { useCallback, useEffect, useState } from 'react'

import { api } from '../api/client'
import type { ExperimentView } from '../api/types'
import { Cited } from '../app/Cited'
import { Glyph, type GlyphName } from '../app/icons'

const CONDITIONS: Record<string, { label: string; icon: GlyphName }> = {
  morning: { label: 'Morning', icon: 'sun' },
  evening: { label: 'Evening', icon: 'moon' },
}
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null)
const pts = (x: number) => String(Math.round(x * 100))

/** The headline of an experiment, in plain words. */
function verdictLine(e: ExperimentView): { title: string; tone: 'win' | 'even' | 'running' } {
  if (e.status === 'running') return { title: 'Running', tone: 'running' }
  if (e.verdict === 'evening') return { title: 'Evening wins', tone: 'win' }
  if (e.verdict === 'morning') return { title: 'Morning wins', tone: 'win' }
  return { title: 'Too close to call', tone: 'even' }
}

function Experiment({ e, onStop }: { e: ExperimentView; onStop: () => void }) {
  const { title, tone } = verdictLine(e)
  const scores = e.scores ?? {}
  const winner = e.verdict === 'morning' || e.verdict === 'evening' ? e.verdict : null
  const p = e.p_evening_better ?? null
  const sure = p === null ? null : winner === 'morning' ? 1 - p : p
  return (
    <section className="card experiment">
      <div className="experiment__head">
        <h2>{e.hypothesis}</h2>
        <span className={`experiment__status experiment__status--${tone}`}>
          {tone === 'running' && <span className="experiment__pulse" aria-hidden="true" />}
          {title}
        </span>
      </div>
      <p className="muted small">
        Games: {e.games.join(', ')} · {e.sessions_per_condition} sessions at each time of day
      </p>

      <ul className="experiment__arms">
        {Object.entries(e.progress).map(([condition, done]) => {
          const c = CONDITIONS[condition] ?? { label: condition, icon: 'clock' as GlyphName }
          const own = scores[condition] ?? []
          const m = mean(own)
          return (
            <li
              key={condition}
              className={`experiment__arm${winner === condition ? ' experiment__arm--win' : ''}`}
            >
              <span className="experiment__label">
                <Glyph name={c.icon} />
                {c.label}
              </span>
              <span className="experiment__track" aria-hidden="true">
                {m !== null && <span className="experiment__bar" style={{ width: `${pts(m)}%` }} />}
                {own.map((s, i) => (
                  <span key={i} className="experiment__dot" style={{ left: `${pts(s)}%` }} />
                ))}
              </span>
              <span className="experiment__value">
                {m !== null && <strong>{pts(m)}% </strong>}
                <span className="muted small">
                  {done} of {e.sessions_per_condition}
                </span>
              </span>
            </li>
          )
        })}
      </ul>

      {e.status !== 'running' && e.interval && (
        <div className={`experiment__verdict experiment__verdict--${tone}`}>
          <p className="experiment__big">{title}</p>
          <p>
            {winner && sure !== null
              ? `Lodestar is ${pts(sure)}% sure the ${winner} is better for you. `
              : 'Neither time of day is clearly better yet. '}
            Evening minus morning: likely {pts(e.interval[0] ?? 0)} to {pts(e.interval[1] ?? 0)}{' '}
            points.
          </p>
        </div>
      )}
      {e.summary && (
        <details className="experiment__how">
          <summary>How Lodestar worked this out</summary>
          <p data-testid="experiment-result">
            <Cited text={e.summary} />
          </p>
        </details>
      )}
      {e.status === 'running' && (
        <button type="button" className="small" onClick={onStop}>
          Stop this experiment
        </button>
      )}
    </section>
  )
}

/** Personal experiments (docs/plan/09, 13; UW10). Each one tests an idea about you, like "I'm
 * sharper in the evening": the same games at both times, then a verdict with how sure it is.
 * Inconclusive results say so. */
export function Experiments({ onAsk }: { onAsk: () => void }) {
  const [list, setList] = useState<ExperimentView[] | null>(null)
  const load = useCallback(() => {
    api.experiments().then(setList, () => {
      setList([])
    })
  }, [])
  useEffect(load, [load])

  if (list === null) return <p className="muted">Loading…</p>
  const running = list.some((e) => e.status === 'running')
  return (
    <div className="stack" data-testid="experiments">
      <section className="experiments__intro">
        <ol className="experiments__steps">
          <li>
            <strong>Pick an idea</strong>
            <span>&ldquo;I&apos;m sharper in the morning.&rdquo;</span>
          </li>
          <li>
            <strong>Play at both times</strong>
            <span>The same games, a few sessions each.</span>
          </li>
          <li>
            <strong>Get a verdict</strong>
            <span>Which time wins, and how sure Lodestar is.</span>
          </li>
        </ol>
        {!running && (
          <button type="button" className="primary" onClick={onAsk}>
            Start one
          </button>
        )}
      </section>
      {list.map((e) => (
        <Experiment
          key={e.exp_id}
          e={e}
          onStop={() => {
            void api.cancelExperiment(e.exp_id).then(load)
          }}
        />
      ))}
    </div>
  )
}
