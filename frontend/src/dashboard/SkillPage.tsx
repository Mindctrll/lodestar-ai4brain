import type { ForecastView, ProgressView, Registry, TwinView } from '../api/types'
import { SkillCurve } from './charts'

const BADGE: Record<string, string> = {
  established: 'Well established in research',
  moderate: 'Some research support',
  experimental: 'Experimental: treat with care',
}

/** One skill (docs/plan/13, night sky "tap a constellation"): what it is, how it's measured, its
 * curve with the forecast, and what can bias it. */
export function SkillPage({
  dim,
  registry,
  twin,
  progress,
  forecast,
  onBack,
}: {
  dim: string
  registry: Registry
  twin: TwinView
  progress: ProgressView
  forecast: ForecastView[]
  onBack: () => void
}) {
  const def = registry.dimensions.find((d) => d.id === dim)
  if (!def) return null
  const view = twin.dims.find((d) => d.dim === dim && d.n > 0)
  const band = forecast.find((f) => f.dim === dim)
  const games = registry.games.filter((g) => g.available && dim in g.dims)
  return (
    <section className="card skill" data-testid="skill-page">
      <button type="button" className="link" onClick={onBack}>
        ← Back to the sky
      </button>
      <h2>{def.name}</h2>
      <p>{def.plain}.</p>
      <p>
        <span className={`badge badge--${def.badge}`}>{BADGE[def.badge] ?? def.badge}</span>
      </p>
      {view ? (
        <p className={view.still_learning ? 'muted' : ''}>
          Estimate {Math.round(view.percent)}%, likely {Math.round(view.percent_low)}-
          {Math.round(view.percent_high)}% ({view.norms} norms)
          {view.still_learning ? '. Still learning about you.' : '.'}
        </p>
      ) : (
        <p className="muted">Not measured yet.</p>
      )}
      <SkillCurve
        twin={twin}
        dim={dim}
        forecast={band}
        strips={progress.life_context}
        name={def.name}
      />
      {band && (
        <p className="muted small">
          Forecast after {band.sessions_ahead} more sessions: {Math.round(band.median)}%, likely{' '}
          {Math.round(band.low)}-{Math.round(band.high)}%. {band.note}
        </p>
      )}
      <h3>Measured by</h3>
      <ul className="lines">
        {games.map((g) => (
          <li key={g.id}>
            <strong>{g.name}</strong> <span className="muted">· {g.does}</span>
          </li>
        ))}
      </ul>
      <h3>What can bias it</h3>
      <p className="muted">{def.biases.join(', ')}.</p>
      {def.note && <p className="muted">{def.note}</p>}
    </section>
  )
}
