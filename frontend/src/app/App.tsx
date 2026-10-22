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
import { Onboarding } from './Onboarding'
import { Settings } from './Settings'
import { useSession } from './useSession'

const NAV: { id: Panel; label: string; icon: ReactNode }[] = [
  { id: 'twin', label: 'Brain Twin', icon: <path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" /> },
  { id: 'progress', label: 'Progress', icon: <path d="M4 18l5-6 4 3 7-9M15 6h5v5" /> },
  {
    id: 'experiments',
    label: 'Experiments',
    icon: <path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3" />,
  },
  {
    id: 'agent',
    label: 'Agent',
    icon: <path d="M5 6h4v4H5zM15 6h4v4h-4zM10 16h4v4h-4zM7 10v3h10v-3M12 13v3" />,
  },
  {
    id: 'acs',
    label: 'AI collaboration',
    icon: <path d="M4 8h12l-3-3M20 16H8l3 3" />,
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: (
      <path d="M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM4 12h2M18 12h2M12 4v2M12 18v2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M6.3 17.7l1.4-1.4M16.3 7.7l1.4-1.4" />
    ),
  },
]

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
  const [persona, setPersona] = useState<Persona>('zitouna')
  // Voice in, voice out: once someone talks to Najma, replies are spoken too (and always shown).
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
          Najma
        </p>
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
  const title = NAV.find((n) => n.id === panel)?.label ?? ''

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
        <section className="panel-block panel-block--sky">
          <NightSky registry={registry} dims={twin.dims} pulse={dash.updates} onSelect={setSkill} />
        </section>
        <section className="panel-block" aria-label="Ask your Twin">
          <h3>Ask your Twin</h3>
          <form
            className="inline-ask"
            onSubmit={(e) => {
              e.preventDefault()
              const said = twinAsk.trim()
              setTwinAsk('')
              if (said) void session.send(`Twin, ${said}`)
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
          <p className="muted small">The Twin answers in the conversation.</p>
        </section>
        <section className="panel-block">
          <h3>All skills at a glance</h3>
          <Radar twin={twin} registry={registry} />
        </section>
      </>
    )
  } else if (panel === 'progress' && registry && twin && progress) {
    body = (
      <>
        <section className="panel-block">
          <h3>Goals</h3>
          <Goals goals={goals} />
        </section>
        <section className="panel-block">
          <h3>Each skill over time</h3>
          <p className="muted small">
            Line: estimate. Shaded: the 80% range. Dashed: the forecast for the next sessions.
            Orange strips: what you told Najma about your days.
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
          <h3>Change by week</h3>
          <WeekHeatmap progress={progress} name={dimName} />
        </section>
        <section className="panel-block">
          <h3>When you do best</h3>
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
        <p className="muted">
          From moments in play: checking the AI&apos;s work, trying before asking, trying again
          after a miss, knowing how sure you are, and taking breaks.
        </p>
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

  return (
    <div className={`shell${playing ? ' shell--playing' : ''}${panel ? ' shell--panel' : ''}`}>
      <header className="topbar">
        <p className="brand">
          <span className="brand__mark" aria-hidden="true" />
          Najma
          {localMode && (
            <span className="badge" title="Najma uses the model on this server">
              Local mode
            </span>
          )}
        </p>
        <nav aria-label="Main" className="topnav">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className="topnav__item"
              aria-current={panel === item.id ? 'page' : undefined}
              aria-label={item.label}
              title={item.label}
              onClick={() => {
                open(item.id)
              }}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                {item.icon}
              </svg>
              <span className="topnav__label">{item.label}</span>
            </button>
          ))}
        </nav>
      </header>
      <SignalIndicator />

      <div className="workspace">
        <main className="stage">
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
          <aside className="sheet" role="dialog" aria-label={title} data-panel={panel}>
            <header className="sheet__head">
              <h2>{title}</h2>
              <button
                type="button"
                className="icon-button"
                aria-label="Close panel"
                onClick={() => {
                  setPanel(null)
                }}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </header>
            <div className="sheet__body">{body ?? <p className="muted">Loading…</p>}</div>
          </aside>
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
