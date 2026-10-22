import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { ModelCard } from '../api/types'
import { Glyph, Heading, type GlyphName } from '../app/icons'

/** The system in one picture: what talks to what (docs/plan/02). */
const LAYERS: { title: string; items: { icon: GlyphName; name: string; what: string }[] }[] = [
  {
    title: 'You',
    items: [
      { icon: 'chat', name: 'Web app', what: 'Chat, games, voice' },
      { icon: 'terminal', name: 'Terminal', what: 'The same agent in a CLI' },
    ],
  },
  {
    title: 'The agent',
    items: [
      { icon: 'route', name: 'LangGraph agent', what: '22 steps: perceive, decide, play, talk' },
      { icon: 'spark', name: 'Your AI model', what: 'Your own key, or a local model' },
    ],
  },
  {
    title: 'The science',
    items: [
      { icon: 'target', name: 'Scoring engine', what: 'Bayesian skill estimates with ranges' },
      { icon: 'trend', name: 'Learned models', what: 'Forecast, rhythm, fatigue, next game' },
    ],
  },
  {
    title: 'Memory',
    items: [
      { icon: 'database', name: 'Postgres', what: 'Every event, append-only' },
      { icon: 'pulse', name: 'Qdrant', what: 'Searchable memories, per user' },
      { icon: 'list', name: 'Markdown', what: 'Notes you can read' },
    ],
  },
]

/** Models that are rules or online learners rather than trained artefacts. */
const BUILT_IN: { title: string; does: string; numbers: [string, string][] }[] = [
  {
    title: 'Fatigue point',
    does: 'Finds the minute in a session when your answers start to slow, from your own history.',
    numbers: [
      ['Method', 'Change points + survival curve'],
      ['Shown as', 'Middle half of sessions'],
    ],
  },
  {
    title: 'Best next game',
    does: 'Learns which game moves each skill most for you, and balances trying and repeating.',
    numbers: [
      ['Method', 'Thompson-sampling bandit'],
      ['Learns', 'From every round you play'],
    ],
  },
]

/** The last `make sim` run: 200 simulated users with known true skills, 10 sessions each
 * (docs/plan/15; the full table is docs/figures/sim_summary.md). */
const SIMULATOR: [string, string, string][] = [
  ['Finds your true skill after 3 sessions (correlation)', '0.82', 'above 0.80'],
  ['80% ranges that contain the true skill', '80%', '75% to 85%'],
  ['Success rate in Balanced mode', '78%', 'about 80%'],
  ['Widest range left after the warm-up (SD)', '0.65', 'below 0.80'],
  ['Bad data caught (precision / recall)', '100% / 100%', 'above 90% / 80%'],
]

const RULES: [GlyphName, string][] = [
  ['shield', 'No health labels, ever. A check screens every reply for them.'],
  ['target', 'Every number the coach says comes from a cited fact.'],
  ['trend', 'Every prediction is shown as a range, never a single number.'],
  ['ear', 'Camera and voice cues never change your profile or scores.'],
  ['database', 'Memory searches only ever see your own data.'],
  ['spark', 'Your AI key is encrypted, never logged, and shown only as its last 4 characters.'],
]

/** How Lodestar works, for the curious (docs/plan/02, 10, 15): the architecture, each model with
 * its evaluation, the simulator's results and the rules the code enforces. */
export function About() {
  const [models, setModels] = useState<ModelCard[]>([])
  useEffect(() => {
    api.models().then(setModels, () => {
      setModels([])
    })
  }, [])

  return (
    <div className="stack" data-testid="about">
      <section className="card">
        <Heading as="h2" icon="route">
          How it fits together
        </Heading>
        <ol className="arch">
          {LAYERS.map((layer) => (
            <li key={layer.title} className="arch__layer">
              <p className="arch__title">{layer.title}</p>
              <ul>
                {layer.items.map((it) => (
                  <li key={it.name} className="arch__box">
                    <Glyph name={it.icon} />
                    <span>
                      <strong>{it.name}</strong>
                      <span>{it.what}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </section>

      <section className="card">
        <Heading as="h2" icon="spark">
          The models
        </Heading>
        <ul className="models">
          {models.map((m) => (
            <li key={m.name} className="model">
              <p className="model__name">{m.title}</p>
              <p className="model__does">{m.does}</p>
              <dl>
                {m.headline.map((h) => (
                  <div key={h.label}>
                    <dt>{h.label}</dt>
                    <dd>{h.value}</dd>
                  </div>
                ))}
              </dl>
              <p className="model__version">
                Trained{' '}
                {new Date(m.trained_at).toLocaleDateString('en-GB', {
                  day: 'numeric',
                  month: 'short',
                  year: 'numeric',
                })}
              </p>
            </li>
          ))}
          {BUILT_IN.map((m) => (
            <li key={m.title} className="model">
              <p className="model__name">{m.title}</p>
              <p className="model__does">{m.does}</p>
              <dl>
                {m.numbers.map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <Heading as="h2" icon="check">
          Tested on 200 simulated people
        </Heading>
        <p className="muted">
          Each simulated person has a known true skill level. Lodestar never sees it, plays 10
          sessions with them, and is checked against the truth.
        </p>
        <table className="sim">
          <thead>
            <tr>
              <th>What we check</th>
              <th>Result</th>
              <th>Target</th>
            </tr>
          </thead>
          <tbody>
            {SIMULATOR.map(([what, result, target]) => (
              <tr key={what}>
                <td>{what}</td>
                <td>
                  <span className="sim__pass">
                    <Glyph name="check" />
                    {result}
                  </span>
                </td>
                <td className="muted">{target}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <Heading as="h2" icon="shield">
          Rules the code enforces
        </Heading>
        <ul className="rules">
          {RULES.map(([icon, text]) => (
            <li key={text}>
              <Glyph name={icon} />
              {text}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
