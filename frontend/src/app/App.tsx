import { useEffect, useState } from 'react'

import { adoptSignIn, api, forgetUser, hasUser } from '../api/client'
import type { Receipt } from '../api/types'
import { AcsPanel } from '../dashboard/AcsPanel'
import { Agent } from '../dashboard/Agent'
import { HourHeatmap, Radar, SkillCurve, WeekHeatmap } from '../dashboard/charts'
import { Goals } from '../dashboard/Goals'
import { NightSky } from '../dashboard/NightSky'
import { SkillPage } from '../dashboard/SkillPage'
import { useDashboard } from '../dashboard/useDashboard'
import { DecisionCard } from './DecisionCard'
import { Onboarding } from './Onboarding'
import { Practice } from './Practice'
import { Settings } from './Settings'
import { useSession } from './useSession'

type View = 'home' | 'twin' | 'progress' | 'agent' | 'acs' | 'settings'

const NAV: { id: View; label: string; icon: string }[] = [
  { id: 'home', label: 'Home', icon: '⌂' },
  { id: 'twin', label: 'Brain Twin', icon: '✦' },
  { id: 'progress', label: 'Progress', icon: '↗' },
  { id: 'agent', label: 'Agent', icon: '◎' },
  { id: 'acs', label: 'AI collaboration', icon: '⇄' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
]

function greeting(now: Date): string {
  const h = now.getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export function App() {
  const session = useSession()
  const [registered, setRegistered] = useState(() => {
    adoptSignIn()
    return hasUser()
  })
  const [view, setView] = useState<View>('home')
  const [skill, setSkill] = useState<string | null>(null)
  const [why, setWhy] = useState<string | null>(null)
  const [localMode, setLocalMode] = useState(false)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const dash = useDashboard(registered)
  const { registry, twin, progress, forecast, goals, acs, decisions } = dash

  const checkLlm = () => {
    Promise.all([api.llm(), api.consent()]).then(
      ([llm, consent]) => {
        const cloud = consent.switches.some((s) => s.id === 'cloud_ai' && s.granted)
        setLocalMode(llm.selection.mode !== 'hosted' || !cloud)
      },
      () => {
        setLocalMode(false)
      },
    )
  }

  useEffect(() => {
    if (registered) checkLlm()
  }, [registered])

  /** A decision option ("working_memory" or "working_memory:echo") in plain words. */
  const optionName = (option: string): string => {
    const [dim = option, gameId] = option.split(':')
    const dimName = registry?.dimensions.find((d) => d.id === dim)?.name ?? dim
    const gameName = gameId ? registry?.games.find((g) => g.id === gameId)?.name : undefined
    return gameName ? `${dimName}, ${gameName}` : dimName
  }
  const dimName = (id: string) => registry?.dimensions.find((d) => d.id === id)?.name ?? id
  const now = new Date()
  const playing = session.state.phase === 'playing'

  if (!registered) {
    return (
      <main className="app app--narrow">
        {receipt ? (
          <section className="card" data-testid="receipt">
            <h2>Everything is deleted</h2>
            <p>{receipt.message}</p>
            <p className="muted">Najma keeps only a receipt with these counts, not who you were.</p>
            <button
              type="button"
              className="primary"
              onClick={() => {
                window.location.assign('/')
              }}
            >
              Start again
            </button>
          </section>
        ) : (
          <Onboarding
            onDone={() => {
              setRegistered(true)
            }}
          />
        )}
      </main>
    )
  }

  const measured = twin?.dims.filter((d) => d.n > 0) ?? []

  return (
    <div className={`shell${playing ? ' shell--playing' : ''}`}>
      <aside className="sidebar">
        <p className="brand">Najma</p>
        <nav aria-label="Main">
          <ul>
            {NAV.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className="nav-item"
                  aria-current={view === item.id ? 'page' : undefined}
                  onClick={() => {
                    setView(item.id)
                    setSkill(null)
                  }}
                >
                  <span aria-hidden="true">{item.icon}</span> {item.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        {localMode && (
          <p className="sidebar__note">
            <span className="badge" title="Najma uses the model on this server">
              Local mode
            </span>
          </p>
        )}
      </aside>

      <main className="main">
        <header className="page-head">
          <p className="muted">
            {now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}
          </p>
          <h1>{view === 'home' ? greeting(now) : NAV.find((n) => n.id === view)?.label}</h1>
          {view === 'home' && progress && (
            <ul className="pills" aria-label="Your week">
              <li>
                <strong>{progress.stats.streak_days}</strong> day streak
              </li>
              <li>
                <strong>{progress.stats.rounds_this_week}</strong> rounds this week
              </li>
              <li>
                <strong>
                  {progress.stats.skills_measured}/{progress.stats.skills_total}
                </strong>{' '}
                skills measured
              </li>
            </ul>
          )}
        </header>

        {dash.error && (
          <p role="alert" className="card">
            Couldn&apos;t load your dashboard: {dash.error}
          </p>
        )}

        {view === 'home' && (
          <div className="grid grid--home">
            <div className="grid__main">
              <Practice session={session} registry={registry} setWhy={setWhy} />
            </div>
            {!playing && (
              <div className="grid__side">
                {registry && twin && (
                  <section className="card card--sky">
                    <h2>Your Brain Twin</h2>
                    <NightSky
                      registry={registry}
                      dims={twin.dims}
                      compact
                      pulse={dash.updates}
                      onSelect={(dim) => {
                        setView('twin')
                        setSkill(dim)
                      }}
                    />
                  </section>
                )}
                <section className="card">
                  <h2>Goals</h2>
                  <Goals goals={goals} />
                </section>
              </div>
            )}
          </div>
        )}

        {view === 'twin' && registry && twin && progress && (
          <>
            {skill ? (
              <SkillPage
                dim={skill}
                registry={registry}
                twin={twin}
                progress={progress}
                forecast={forecast}
                onBack={() => {
                  setSkill(null)
                }}
              />
            ) : (
              <>
                <section className="card card--sky">
                  <h2>Night sky</h2>
                  <NightSky
                    registry={registry}
                    dims={twin.dims}
                    pulse={dash.updates}
                    onSelect={setSkill}
                  />
                </section>
                <section className="card">
                  <h2>All skills at a glance</h2>
                  <Radar twin={twin} registry={registry} />
                </section>
              </>
            )}
          </>
        )}

        {view === 'progress' && registry && twin && progress && (
          <>
            <section className="card">
              <h2>Goals</h2>
              <Goals goals={goals} />
            </section>
            <section className="card">
              <h2>Each skill over time</h2>
              <p className="muted small">
                Line: estimate. Shaded: the 80% range. Dashed: the forecast for the next sessions.
                Orange strips: what you told Najma about your days.
              </p>
              <div className="curves">
                {measured.map((d) => (
                  <div key={d.dim} className="curves__item">
                    <h3>{dimName(d.dim)}</h3>
                    <SkillCurve
                      twin={twin}
                      dim={d.dim}
                      forecast={forecast.find((f) => f.dim === d.dim)}
                      strips={progress.life_context}
                      name={dimName(d.dim)}
                    />
                  </div>
                ))}
              </div>
            </section>
            <div className="grid grid--two">
              <section className="card">
                <h2>Change by week</h2>
                <WeekHeatmap progress={progress} name={dimName} />
              </section>
              <section className="card">
                <h2>When you do best</h2>
                <HourHeatmap progress={progress} />
              </section>
            </div>
          </>
        )}

        {view === 'agent' && (
          <Agent
            timeline={session.state.timeline}
            sessionId={session.state.sessionId}
            decisions={decisions}
            onWhy={setWhy}
          />
        )}

        {view === 'acs' && acs && (
          <section className="card">
            <h2>How you work with AI</h2>
            <p className="muted small">
              From moments in play: checking the AI&apos;s work, trying before asking, trying again
              after a miss, knowing how sure you are, and taking breaks.
            </p>
            <AcsPanel acs={acs} />
          </section>
        )}

        {view === 'settings' && (
          <Settings
            onLlmChange={checkLlm}
            onDeleted={(r) => {
              forgetUser()
              setReceipt(r)
              setRegistered(false)
            }}
          />
        )}

        {why && (
          <DecisionCard
            decisionId={why}
            name={optionName}
            onClose={() => {
              setWhy(null)
            }}
          />
        )}
      </main>
    </div>
  )
}
