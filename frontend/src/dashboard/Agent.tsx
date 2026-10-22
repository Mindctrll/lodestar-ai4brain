import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { AgentEvent, Decision, TraceRow } from '../api/types'
import { Heading } from '../app/icons'

/** The graph's nodes in the order a session usually visits them (docs/plan/03). */
const LANES: { title: string; nodes: string[] }[] = [
  {
    title: 'Perceive',
    nodes: ['ingest', 'load_twin', 'recall_memory', 'read_affect', 'read_context', 'forecast'],
  },
  { title: 'Decide', nodes: ['safety_gate', 'route_intent', 'plan_next', 'prepare_exercise'] },
  { title: 'Play', nodes: ['play', 'score_update', 'monitor'] },
  { title: 'Talk', nodes: ['converse', 'confirm', 'use_tool', 'answer', 'reflect', 'coach'] },
  { title: 'Remember', nodes: ['respond', 'remember', 'consolidate'] },
]

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

/** Show the agent at work (docs/plan/13): the graph lighting up live, every decision with its
 * reason and candidates, and the trace of a session. */
export function Agent({
  timeline,
  sessionId,
  decisions,
  onWhy,
}: {
  timeline: AgentEvent[]
  sessionId: string | null
  decisions: Decision[]
  onWhy: (decisionId: string) => void
}) {
  const states = nodeStates(timeline)
  const [trace, setTrace] = useState<TraceRow[] | null>(null)
  const degraded = timeline.flatMap((e) => (e.kind === 'degraded' ? [e] : []))

  useEffect(() => {
    if (!sessionId) return
    api.trace(sessionId).then(setTrace, () => {
      setTrace(null)
    })
  }, [sessionId, timeline.length])

  return (
    <div className="agent stack" data-testid="agent">
      <section className="card">
        <Heading as="h2" icon="pulse">
          The agent, live
        </Heading>
        <p className="muted">
          {sessionId
            ? 'Nodes light up as Lodestar works through your session.'
            : 'Start a session to watch Lodestar work.'}
        </p>
        <div className="graph" role="list" aria-label="Agent graph">
          {LANES.map((lane) => (
            <div key={lane.title} className="graph__lane" role="listitem">
              <p className="graph__title">{lane.title}</p>
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
          ))}
        </div>
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
        {decisions.length === 0 && <p className="muted">No decisions yet.</p>}
        <ul className="decisions">
          {decisions.map((d) => (
            <li key={d.decision_id}>
              <span className="muted small">
                {new Date(d.at).toLocaleString('en-GB', {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                })}{' '}
                · {d.node.replace(/_/g, ' ')}
              </span>
              <p>{d.reason}</p>
              {d.candidates.length > 0 && (
                <button
                  type="button"
                  className="link"
                  onClick={() => {
                    onWhy(d.decision_id)
                  }}
                >
                  See the options it weighed
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      {trace && trace.length > 0 && (
        <section className="card">
          <Heading as="h2" icon="list">
            Trace of this session
          </Heading>
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
        </section>
      )}
    </div>
  )
}
