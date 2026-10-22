import { useCallback, useEffect, useState } from 'react'

import { api } from '../api/client'
import type { MyData } from '../api/types'
import { Glyph, Heading } from '../app/icons'

const day = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : 'Undated'

/** What Lodestar remembers (docs/plan/04; UW14): the short profile it keeps in core.md, the moments
 * and facts it can search, and what you told it about your days. Every line can be forgotten. */
export function Memory() {
  const [data, setData] = useState<MyData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    api.myData().then(setData, (e: unknown) => {
      setError(e instanceof Error ? e.message : String(e))
    })
  }, [])
  useEffect(load, [load])

  const forget = (work: () => Promise<unknown>) => {
    work().then(load, (e: unknown) => {
      setError(e instanceof Error ? e.message : String(e))
    })
  }

  if (error) return <p role="alert">{error}</p>
  if (!data) return <p className="muted">Loading…</p>
  const moments = data.memories
    .filter((m) => m.collection === 'episodic')
    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
  const facts = data.memories.filter((m) => m.collection === 'facts')

  return (
    <div className="memory" data-testid="memory">
      <ul className="memory__stores">
        <li>
          <Glyph name="list" />
          <strong>{data.core.length}</strong> notes in a Markdown file you can read
        </li>
        <li>
          <Glyph name="database" />
          <strong>{data.memories.length}</strong> memories it can search
        </li>
        <li>
          <Glyph name="calendar" />
          <strong>{data.life_context.length}</strong> things about your days
        </li>
      </ul>

      <section className="panel-block">
        <Heading icon="user">What Lodestar knows about you</Heading>
        {data.core.length === 0 ? (
          <p className="muted">Nothing yet. Lodestar writes this after a few sessions.</p>
        ) : (
          <ul className="notes">
            {data.core.map((line) => (
              <li key={line}>
                <span>{line}</span>
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => {
                    forget(() => api.forgetCoreLine(line))
                  }}
                >
                  Forget
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="memory__cols">
        <section className="panel-block">
          <Heading icon="clock">Moments it remembers</Heading>
          {moments.length === 0 && <p className="muted">No moments yet.</p>}
          <ol className="timeline">
            {moments.map((m) => (
              <li key={m.id}>
                <span className="timeline__when">{day(m.created_at)}</span>
                <div>
                  {m.kind && <span className="timeline__kind">{m.kind}</span>}
                  <p>{m.text}</p>
                  <button
                    type="button"
                    className="link"
                    onClick={() => {
                      forget(() => api.forgetMemory(m.collection, m.id))
                    }}
                  >
                    Forget
                  </button>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <div className="stack">
          <section className="panel-block">
            <Heading icon="check">Facts it has learned</Heading>
            {facts.length === 0 && <p className="muted">No facts yet.</p>}
            <ul className="notes">
              {facts.map((m) => (
                <li key={m.id}>
                  <span>{m.text}</span>
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => {
                      forget(() => api.forgetMemory(m.collection, m.id))
                    }}
                  >
                    Forget
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel-block">
            <Heading icon="calendar">Your days</Heading>
            {data.life_context.length === 0 && (
              <p className="muted">Tell Lodestar things like &ldquo;I slept badly&rdquo;.</p>
            )}
            <ul className="notes">
              {data.life_context.map((c) => (
                <li key={c.context_id}>
                  <span>
                    <strong>{c.label}</strong>{' '}
                    <span className="muted small">
                      {day(c.start)} to {day(c.end)}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => {
                      forget(() => api.forgetLifeContext(c.context_id))
                    }}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
      {!data.memory_available && (
        <p className="muted">Searchable memories can&apos;t be shown right now.</p>
      )}
      <p className="muted small">
        Everything here stays on this server. Forget a line and it is gone; Settings can export or
        delete all of it.
      </p>
    </div>
  )
}
