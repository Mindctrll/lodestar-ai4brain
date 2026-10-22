import { useEffect, useState, type ReactNode } from 'react'

import { SignalIndicator } from '../affect/SignalIndicator'
import { adoptSignIn, api, forgetUser, hasUser } from '../api/client'
import type { Persona, Receipt } from '../api/types'
import { AcsPanel } from '../dashboard/AcsPanel'
import { Agent } from '../dashboard/Agent'
import { HourHeatmap, Radar, SkillCurve, WeekHeatmap } from '../dashboard/charts'
import { Experiments } from '../dashboard/Experiments'
import { Goals } from '../dashboard/Goals'
import { NightSky } from '../dashboard/NightSky'
import { SkillPage } from '../dashboard/SkillPage'
import { useDashboard } from '../dashboard/useDashboard'
import { setSpeakReplies, speakReplies, stopSpeaking } from '../voice/tts'
import { useSpeakReplies } from '../voice/useSpeakReplies'
import { Composer } from './Composer'
import { Conversation, type Panel } from './Conversation'
import { DecisionCard } from './DecisionCard'
import { Heading } from './icons'
import { Onboarding } from './Onboarding'
import { Settings } from './Settings'
import { useSession } from './useSession'

type NavItem = { id: Panel; label: string; icon: ReactNode }

/** Line icons on a 24px grid, drawn with `currentColor`. */
const NAV: NavItem[] = [
  {
    id: 'twin',
    label: 'Brain Twin',
    icon: (
      <path d="M12 3l1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3zM19 3v4M21 5h-4" />
    ),
  },
  {
    id: 'progress',
    label: 'Progress',
    icon: <path d="M3 3v16a2 2 0 0 0 2 2h16M7 15l4-4 3 3 6-6M16 8h4v4" />,
  },
  {
    id: 'experiments',
    label: 'Experiments',
    icon: (
      <path d="M10 2v7.5a2 2 0 0 1-.2.9L4.7 20.6a1 1 0 0 0 .9 1.4h12.8a1 1 0 0 0 .9-1.4l-5.1-10.2a2 2 0 0 1-.2-.9V2M8.5 2h7M7 16h10" />
    ),
  },
  {
    id: 'agent',
    label: 'Agent',
    icon: (
      <path d="M12 8V4H8M6 8h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2zM2 14h2M20 14h2M15 13v2M9 13v2" />
    ),
  },
  {
    id: 'acs',
    label: 'AI collaboration',
    icon: <path d="M8 3L4 7l4 4M4 7h16M16 21l4-4-4-4M20 17H4" />,
  },
]
const SETTINGS: NavItem = {
  id: 'settings',
  label: 'Settings',
  icon: (
    <path d="M20 7h-9M14 17H5M17 20a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM7 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
  ),
}
const ALL = [...NAV, SETTINGS]
const SUBTITLE: Record<Panel, string> = {
  twin: 'Every skill, with how sure Lodestar is about it.',
  progress: 'Your goals and how each skill has moved.',
  experiments: 'Try one change and see if it helps you.',
  agent: 'What Lodestar did, step by step, and why.',
  acs: 'How you work with AI: checking, trying first, and taking breaks.',
  settings: 'Privacy, voice, your AI provider and your data.',
}

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {children}
    </svg>
  )
}

export function App() {
  const session = useSession()
  const [registered, setRegistered] = useState(() => {
    adoptSignIn()
    return hasUser()
  })
  const [panel, setPanel] = useState<Panel | null>(null)
  const [skill, setSkill] = useState<string | null>(null)
  const [why, setWhy] = useState<string | null>(null)
  const [localMode, setLocalMode] = useState(false)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [twinAsk, setTwinAsk] = useState('')
  const dash = useDashboard(registered)
  const [persona, setPersona] = useState<Persona>('willow')
  // Voice in, voice out: once someone talks to Lodestar, replies are spoken too (and always shown).
  const [voiceUsed, setVoiceUsed] = useState(false)
  useSpeakReplies(session.state, persona, voiceUsed || speakReplies())
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
    if (!registered) return
    checkLlm()
    api.me().then(
      (me) => {
        setPersona(me.persona as Persona)
      },
      () => undefined,
    )
  }, [registered])

  // Escape closes the top-most popup.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (why) setWhy(null)
      else if (panel) setPanel(null)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
    }
  }, [why, panel])

  /** A decision option ("working_memory" or "working_memory:echo") in plain words. */
  const optionName = (option: string): string => {
    const [dim = option, gameId] = option.split(':')
    const dimName = registry?.dimensions.find((d) => d.id === dim)?.name ?? dim
    const gameName = gameId ? registry?.games.find((g) => g.id === gameId)?.name : undefined
    return gameName ? `${dimName}, ${gameName}` : dimName
  }
  const dimName = (id: string) => registry?.dimensions.find((d) => d.id === id)?.name ?? id
  const playing = session.state.phase === 'playing'
  const open = (id: Panel, dim?: string) => {
    setPanel(id)
    setSkill(dim ?? null)
  }

  if (!registered) {
    return (
      <main className="solo">
        <p className="brand brand--solo">
          <span className="brand__mark" aria-hidden="true" />
          Lodestar
        </p>
        {receipt ? (
          <section className="card" data-testid="receipt">
            <h2>Everything is deleted</h2>
            <p>{receipt.message}</p>
            <p className="muted">
              Lodestar keeps only a receipt with these counts, not who you were.
            </p>
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
  const current = ALL.find((n) => n.id === panel)
  const title = current?.label ?? ''

  let body: ReactNode = null
  if (panel === 'twin' && registry && twin && progress) {
    body = skill ? (
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
        <section aria-label="Skill map">
          <NightSky registry={registry} dims={twin.dims} pulse={dash.updates} onSelect={setSkill} />
        </section>
        <section className="panel-block" aria-label="Ask your Twin">
          <Heading icon="chat">Ask your Twin</Heading>
          <form
            className="inline-ask"
            onSubmit={(e) => {
              e.preventDefault()
              const said = twinAsk.trim()
              setTwinAsk('')
              if (said) {
                setPanel(null)
                void session.send(`Twin, ${said}`)
              }
            }}
          >
            <input
              value={twinAsk}
              maxLength={2000}
              placeholder="e.g. when am I sharpest?"
              aria-label="Your question for the Twin"
              onChange={(e) => {
                setTwinAsk(e.target.value)
              }}
            />
            <button type="submit" disabled={!twinAsk.trim()}>
              Ask
            </button>
          </form>
          <p className="muted small">The answer shows up in the conversation.</p>
        </section>
        <section className="panel-block">
          <Heading icon="radar">All skills at a glance</Heading>
          <Radar twin={twin} registry={registry} />
        </section>
      </>
    )
  } else if (panel === 'progress' && registry && twin && progress) {
    body = (
      <>
        <section className="panel-block">
          <Heading icon="target">Goals</Heading>
          <Goals goals={goals} />
        </section>
        <section className="panel-block">
          <Heading icon="trend">Each skill over time</Heading>
          <p className="muted small">
            Line: estimate. Shaded: the 80% range. Dashed: the forecast for the next sessions.
            Orange strips: what you told Lodestar about your days.
          </p>
          <div className="curves">
            {measured.map((d) => (
              <div key={d.dim} className="curves__item">
                <h4>{dimName(d.dim)}</h4>
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
        <section className="panel-block">
          <Heading icon="calendar">Change by week</Heading>
          <WeekHeatmap progress={progress} name={dimName} />
        </section>
        <section className="panel-block">
          <Heading icon="clock">When you do best</Heading>
          <HourHeatmap progress={progress} />
        </section>
      </>
    )
  } else if (panel === 'experiments') {
    body = (
      <Experiments
        onAsk={() => {
          setPanel(null)
          void session.send('I want to run an experiment')
        }}
      />
    )
  } else if (panel === 'agent') {
    body = (
      <Agent
        timeline={session.state.timeline}
        sessionId={session.state.sessionId}
        decisions={decisions}
        onWhy={setWhy}
      />
    )
  } else if (panel === 'acs' && acs) {
    body = (
      <section className="panel-block">
        <AcsPanel acs={acs} />
      </section>
    )
  } else if (panel === 'settings') {
    body = (
      <Settings
        onVoiceChange={(speak) => {
          setSpeakReplies(speak)
          if (!speak) {
            setVoiceUsed(false)
            stopSpeaking()
          }
        }}
        onLlmChange={checkLlm}
        onDeleted={(r) => {
          forgetUser()
          setReceipt(r)
          setRegistered(false)
        }}
      />
    )
  }

  const navButton = (item: NavItem) => (
    <button
      key={item.id}
      type="button"
      className="rail__item"
      aria-current={panel === item.id ? 'page' : undefined}
      aria-label={item.label}
      title={item.label}
      onClick={() => {
        open(item.id)
      }}
    >
      <Icon>{item.icon}</Icon>
      <span className="rail__label">{item.label}</span>
    </button>
  )
  const home =
    session.state.feed.length === 0 &&
    (session.state.phase === 'home' || session.state.phase === 'resumable')

  return (
    <div className={`shell${playing ? ' shell--playing' : ''}${panel ? ' shell--panel' : ''}`}>
      <aside className="rail">
        <p className="brand">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__name">Lodestar</span>
        </p>
        <nav aria-label="Main" className="rail__nav">
          <button
            type="button"
            className="rail__item"
            aria-current={panel === null ? 'page' : undefined}
            aria-label="Conversation"
            title="Conversation"
            onClick={() => {
              setPanel(null)
            }}
          >
            <Icon>
              <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z" />
            </Icon>
            <span className="rail__label">Conversation</span>
          </button>
          <p className="rail__group">Your mind</p>
          {NAV.slice(0, 3).map(navButton)}
          <p className="rail__group">Behind the scenes</p>
          {NAV.slice(3).map(navButton)}
          <span className="rail__spacer" />
          {localMode && (
            <p className="rail__note" title="Lodestar uses the model on this server">
              <span className="rail__dot" aria-hidden="true" />
              <span className="rail__label">Local mode</span>
            </p>
          )}
          {navButton(SETTINGS)}
        </nav>
      </aside>
      <SignalIndicator />

      <div className="workspace">
        <main className={`stage${home ? ' stage--home' : ''}`} hidden={panel !== null}>
          {dash.error && (
            <p role="alert" className="notice">
              Couldn&apos;t load your Twin: {dash.error}
            </p>
          )}
          <Conversation
            session={session}
            registry={registry}
            twin={twin}
            goals={goals}
            progress={progress}
            setWhy={setWhy}
            onOpen={open}
          />
          {!playing && session.state.phase !== 'resumable' && (
            <Composer
              session={session}
              onVoice={(text) => {
                setVoiceUsed(true)
                void session.send(text, 'voice')
              }}
            />
          )}
        </main>

        {panel && (
          <section className="page" aria-label={title} data-panel={panel}>
            <header className="page__head">
              <div className="page__title">
                {current && (
                  <span className="page__icon">
                    <Icon>{current.icon}</Icon>
                  </span>
                )}
                <h1>{title}</h1>
              </div>
              <p className="muted">{SUBTITLE[panel]}</p>
            </header>
            <div className="page__body">{body ?? <p className="muted">Loading…</p>}</div>
          </section>
        )}
      </div>

      {why && (
        <div
          className="backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setWhy(null)
          }}
        >
          <DecisionCard
            decisionId={why}
            name={optionName}
            onClose={() => {
              setWhy(null)
            }}
          />
        </div>
      )}
    </div>
  )
}
