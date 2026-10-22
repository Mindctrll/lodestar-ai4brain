import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { AgentEvent, Decision, TraceRow } from '../api/types'
import { Glyph, Heading, type GlyphName } from '../app/icons'

/** The graph's nodes in the order a session usually visits them (docs/plan/03), with what each
 * stage does in plain words. */
const LANES: { title: string; icon: GlyphName; does: string; nodes: string[] }[] = [
  {
    title: 'Perceive',
    icon: 'ear',
    does: 'Reads your profile, memories, mood and plans.',
    nodes: ['ingest', 'load_twin', 'recall_memory', 'read_affect', 'read_context', 'forecast'],
  },
  {
    title: 'Decide',
    icon: 'route',
    does: 'Checks safety, works out what you asked, picks the next game.',
    nodes: ['safety_gate', 'route_intent', 'plan_next', 'prepare_exercise'],
  },
  {
    title: 'Play',
    icon: 'target',
    does: 'Runs the game, scores it, watches for tiredness.',
    nodes: ['play', 'score_update', 'monitor'],
  },
  {
    title: 'Talk',
    icon: 'chat',
    does: 'Answers and coaches with cited facts; asks before changes.',
    nodes: ['converse', 'confirm', 'use_tool', 'answer', 'reflect', 'coach'],
  },
  {
    title: 'Remember',
    icon: 'database',
    does: 'Keeps what matters for next time.',
    nodes: ['respond', 'remember', 'consolidate'],
  },
]
const SHOWN = 6

type NodeState = 'idle' | 'running' | 'done' | 'error'

function nodeStates(timeline: AgentEvent[]): Map<string, { state: NodeState; ms?: number }> {
  const out = new Map<string, { state: NodeState; ms?: number }>()
  for (const e of timeline) {
    if (e.kind !== 'node') continue
    const state: NodeState =
      e.status === 'start' ? 'running' : e.status === 'done' ? 'done' : 'error'
    out.set(e.node, e.ms === undefined ? { state } : { state, ms: e.ms })
  }
  return out
}

/** One decision: what Lodestar picked, why, and how the options scored against each other. */
function DecisionCard({
  d,
  name,
  onWhy,
}: {
  d: Decision
  name: (option: string) => string
  onWhy: (decisionId: string) => void
}) {
  const options = [...d.candidates].sort((a, b) => b.score - a.score).slice(0, 3)
  const top = Math.max(...options.map((o) => o.score), 0.0001)
  return (
    <li className="decision">
      <div className="decision__head">
        <span className="decision__chip">{d.node.replace(/_/g, ' ')}</span>
        <span className="muted small">
          {new Date(d.at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}
        </span>
      </div>
      <p className="decision__picked">
        <Glyph name="check" />
        {name(d.chosen)}
      </p>
      <p className="decision__reason">{d.reason}</p>
      {options.length > 1 && (
        <ul className="decision__options" aria-label="Options it weighed">
          {options.map((o) => (
            <li
              key={o.option}
              className={d.chosen.split(':')[0] === o.option.split(':')[0] ? 'is-chosen' : ''}
            >
              <span className="decision__option">{name(o.option)}</span>
              <span className="decision__bar">
                <span style={{ width: `${String(Math.max(4, (o.score / top) * 100))}%` }} />
              </span>
              <span className="decision__score">{o.score.toFixed(2)}</span>
            </li>
          ))}
        </ul>
      )}
      {d.candidates.length > 0 && (
        <button
          type="button"
          className="link"
          onClick={() => {
            onWhy(d.decision_id)
          }}
        >
          See the full breakdown
        </button>
      )}
    </li>
  )
}

/** Show the agent at work (docs/plan/13): the graph lighting up live, every decision with its
 * reason and candidates, and the trace of a session. */
export function Agent({
  timeline,
  sessionId,
  decisions,
  name = (option) => option,
  onWhy,
}: {
  timeline: AgentEvent[]
  sessionId: string | null
  decisions: Decision[]
  name?: (option: string) => string
  onWhy: (decisionId: string) => void
}) {
  const states = nodeStates(timeline)
  const [trace, setTrace] = useState<TraceRow[] | null>(null)
  const [all, setAll] = useState(false)
  const degraded = timeline.flatMap((e) => (e.kind === 'degraded' ? [e] : []))
  const steps = timeline.filter((e) => e.kind === 'node' && e.status === 'done').length
  const weighed = decisions.length
    ? Math.round(decisions.reduce((n, d) => n + d.candidates.length, 0) / decisions.length)
    : 0

  useEffect(() => {
    if (!sessionId) return
    api.trace(sessionId).then(setTrace, () => {
      setTrace(null)
    })
  }, [sessionId, timeline.length])

  return (
    <div className="agent stack" data-testid="agent">
      <ul className="agent__stats">
        <li>
          <strong>{decisions.length}</strong>
          <span>decisions logged, each with its reason</span>
        </li>
        <li>
          <strong>{LANES.reduce((n, l) => n + l.nodes.length, 0)}</strong>
          <span>steps in Lodestar&apos;s loop</span>
        </li>
        <li>
          <strong>{steps > 0 ? steps : weighed}</strong>
          <span>{steps > 0 ? 'steps run this session' : 'options weighed for each pick'}</span>
        </li>
      </ul>

      <section className="card">
        <Heading as="h2" icon="pulse">
          How Lodestar thinks
        </Heading>
        <p className="muted">
          {sessionId
            ? 'Each step lights up as Lodestar works through your session.'
            : 'Every turn runs through these five stages. Start a session to watch them light up.'}
        </p>
        <ol className="flow" aria-label="Agent graph">
          {LANES.map((lane, i) => (
            <li key={lane.title} className="flow__stage">
              <div className="flow__head">
                <span className="flow__icon">
                  <Glyph name={lane.icon} />
                </span>
                <span className="flow__step">{i + 1}</span>
                <strong>{lane.title}</strong>
              </div>
              <p className="flow__does">{lane.does}</p>
              <div className="flow__nodes">
                {lane.nodes.map((n) => {
                  const s = states.get(n)
                  return (
                    <span
                      key={n}
                      className={`graph__node graph__node--${s?.state ?? 'idle'}`}
                      data-node={n}
                      title={s?.ms !== undefined ? `${n}: ${String(Math.round(s.ms))} ms` : n}
                    >
                      {n.replace(/_/g, ' ')}
                    </span>
                  )
                })}
              </div>
            </li>
          ))}
        </ol>
        {degraded.length > 0 && (
          <p className="muted small">
            Fallbacks this session:{' '}
            {degraded.map((d) => `${d.what} ${d.from} → ${d.to}`).join('; ')}
          </p>
        )}
      </section>

      <section className="card">
        <Heading as="h2" icon="route">
          Decisions and why
        </Heading>
        <p className="muted">
          Before every game Lodestar scores each skill (how unsure it is, how long since you played,
          your goals) and picks the best. Nothing is hidden.
        </p>
        {decisions.length === 0 && <p className="muted">No decisions yet.</p>}
        <ul className="decisions">
          {(all ? decisions : decisions.slice(0, SHOWN)).map((d) => (
            <DecisionCard key={d.decision_id} d={d} name={name} onWhy={onWhy} />
          ))}
        </ul>
        {decisions.length > SHOWN && (
          <button
            type="button"
            className="ghost small"
            onClick={() => {
              setAll(!all)
            }}
          >
            {all ? 'Show fewer' : `Show all ${String(decisions.length)}`}
          </button>
        )}
      </section>

      {trace && trace.length > 0 && (
        <details className="card agent__trace">
          <summary>
            <Heading as="h2" icon="list">
              Step-by-step trace ({trace.length} steps)
            </Heading>
          </summary>
          <table className="trace">
            <thead>
              <tr>
                <th>Node</th>
                <th>Step</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {trace.slice(-60).map((r, i) => (
                <tr key={i}>
                  <td>{r.node}</td>
                  <td>{r.event}</td>
                  <td>{r.ms === null ? '' : `${String(Math.round(r.ms))} ms`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  )
}
