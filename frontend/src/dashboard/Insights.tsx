import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { ForecastView, InsightsView, ProgressView, TwinView } from '../api/types'
import { Glyph, type GlyphName } from '../app/icons'

const pct = (x: number) => `${String(Math.round(x))}%`
const mins = (x: number) => String(Math.round(x))
const BLOCK: Record<string, string> = {
  night: 'Night',
  '6-10': 'Early morning',
  '10-14': 'Late morning',
  '14-18': 'Afternoon',
  '18-22': 'Evening',
  '22-24': 'Late evening',
}

function Insight({
  icon,
  title,
  big,
  children,
  how,
}: {
  icon: GlyphName
  title: string
  big: string
  children?: React.ReactNode
  how: string
}) {
  return (
    <section className="insight">
      <p className="insight__title">
        <span className="insight__icon">
          <Glyph name={icon} />
        </span>
        {title}
      </p>
      <p className="insight__big">{big}</p>
      {children}
      <p className="insight__how">{how}</p>
    </section>
  )
}

/** Share right in each time-of-day block, over every weekday, weighted by answers. */
function byBlock(progress: ProgressView): { label: string; share: number; answers: number }[] {
  const h = progress.by_hour
  return h.hours.map((label, b) => {
    let right = 0
    let answers = 0
    h.weekdays.forEach((_, d) => {
      const n = h.answers[b]?.[d] ?? 0
      const acc = h.accuracy[b]?.[d]
      if (n > 0 && acc !== null && acc !== undefined) {
        right += acc * n
        answers += n
      }
    })
    return { label: BLOCK[label] ?? label, share: answers ? right / answers : 0, answers }
  })
}

/** What the models have learned about this person (docs/plan/10), each reading with its range
 * and the model behind it. The engagement-risk score is never shown; only days played are. */
export function Insights({
  progress,
  forecast,
  twin,
}: {
  progress: ProgressView | null
  forecast: ForecastView[]
  twin: TwinView | null
}) {
  const [data, setData] = useState<InsightsView | null>(null)
  useEffect(() => {
    api.insights().then(setData, () => {
      setData(null)
    })
  }, [])

  const blocks = progress ? byBlock(progress).filter((b) => b.answers >= 20) : []
  const best = [...blocks].sort((a, b) => b.share - a.share)[0]
  const top = Math.max(...blocks.map((b) => b.share), 0.01)
  const now = (dim: string) => twin?.dims.find((d) => d.dim === dim)?.percent
  const ahead = [...forecast].sort((a, b) => b.median - a.median).slice(0, 6)
  const cal = data?.calibration
  const fat = data?.fatigue
  const rhythm = data?.rhythm

  return (
    <div className="insights" data-testid="insights">
      <section className="insight insight--wide">
        <p className="insight__title">
          <span className="insight__icon">
            <Glyph name="trend" />
          </span>
          Where you&apos;re heading
        </p>
        {ahead.length === 0 ? (
          <p className="muted">Lodestar needs three days of practice on a skill to forecast it.</p>
        ) : (
          <>
            <p className="insight__big">
              In {ahead[0]?.sessions_ahead ?? 5} more sessions, your strongest skills look like
              this.
            </p>
            <ul className="heading-to">
              {ahead.map((f) => {
                const today = now(f.dim)
                return (
                  <li key={f.dim}>
                    <span className="heading-to__name">{f.name}</span>
                    <span className="heading-to__scale" aria-hidden="true">
                      <span
                        className="heading-to__band"
                        style={{ left: pct(f.low), width: pct(f.high - f.low) }}
                      />
                      {today !== undefined && (
                        <span className="heading-to__now" style={{ left: pct(today) }} />
                      )}
                      <span className="heading-to__mid" style={{ left: pct(f.median) }} />
                    </span>
                    <span className="heading-to__value">
                      likely {pct(f.low)}-{pct(f.high)}
                    </span>
                  </li>
                )
              })}
            </ul>
            <p className="insight__legend">
              <span className="legend-now" /> today <span className="legend-band" /> where you are
              likely to be
            </p>
          </>
        )}
        <p className="insight__how">
          Growth forecast model, trained on 36,000 players of similar games; it personalises as you
          play.
        </p>
      </section>

      <Insight
        icon="clock"
        title="Your best time"
        big={best ? `You do best in the ${best.label.toLowerCase()}.` : 'Not enough games yet.'}
        how="From every answer you've given, by time of day."
      >
        {blocks.length > 0 && (
          <ul className="bars">
            {blocks.map((b) => (
              <li key={b.label} className={b === best ? 'is-best' : ''}>
                <span className="bars__label">{b.label}</span>
                <span className="bars__track">
                  <span style={{ width: `${String((b.share / top) * 100)}%` }} />
                </span>
                <span className="bars__value">{pct(b.share * 100)}</span>
              </li>
            ))}
          </ul>
        )}
      </Insight>

      <Insight
        icon="pulse"
        title="When you tire"
        big={
          fat
            ? `Your answers start slowing after about ${mins(fat.median)} minutes.`
            : 'No clear point yet.'
        }
        how={
          fat
            ? `Change-point model over your last ${String(fat.sessions)} sessions. Lodestar plans breaks around it.`
            : 'Needs a few longer sessions to find where you slow down.'
        }
      >
        {fat && (
          <div className="tire">
            <div className="tire__track" aria-hidden="true">
              <span
                className="tire__band"
                style={{
                  left: `${String((fat.low / 30) * 100)}%`,
                  width: `${String(((Math.min(fat.high, 30) - fat.low) / 30) * 100)}%`,
                }}
              />
              <span className="tire__mid" style={{ left: `${String((fat.median / 30) * 100)}%` }} />
            </div>
            <p className="tire__axis">
              <span>0</span>
              <span>
                likely {mins(fat.low)}-{mins(fat.high)} min
              </span>
              <span>30 min</span>
            </p>
          </div>
        )}
      </Insight>

      <Insight
        icon="target"
        title="How well you judge yourself"
        big={
          cal
            ? cal.said > cal.high
              ? 'You are a little more sure than you are right.'
              : cal.said < cal.low
                ? 'You are right more often than you think.'
                : 'Your confidence matches how often you are right.'
            : 'Answer a few more "How sure?" questions.'
        }
        how={
          cal
            ? `From ${String(cal.answers)} "How sure?" answers. Knowing this helps you check AI answers too.`
            : 'Lodestar asks "How sure?" after about one answer in ten.'
        }
      >
        {cal && (
          <ul className="bars bars--two">
            <li>
              <span className="bars__label">You said</span>
              <span className="bars__track">
                <span style={{ width: pct(cal.said * 100) }} />
              </span>
              <span className="bars__value">{pct(cal.said * 100)}</span>
            </li>
            <li className="is-best">
              <span className="bars__label">You were right</span>
              <span className="bars__track">
                <span style={{ width: pct(cal.right * 100) }} />
              </span>
              <span className="bars__value">
                {pct(cal.low * 100)}-{pct(cal.high * 100)}
              </span>
            </li>
          </ul>
        )}
      </Insight>

      <Insight
        icon="calendar"
        title="Your rhythm"
        big={
          rhythm
            ? `You played on ${String(rhythm.active_7)} of the last 7 days.`
            : 'Loading your rhythm.'
        }
        how="Lodestar offers a shorter, easier session when your rhythm drops."
      >
        {rhythm && (
          <ul className="rhythm">
            <li>
              <strong>{rhythm.active_prev_7}</strong>
              <span>days the week before</span>
            </li>
            <li>
              <strong>{rhythm.sessions}</strong>
              <span>sessions</span>
            </li>
            <li>
              <strong>{rhythm.rounds}</strong>
              <span>games played</span>
            </li>
          </ul>
        )}
      </Insight>
    </div>
  )
}
