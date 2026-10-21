import { useCallback, useEffect, useState } from 'react'

import { ApiError, api, signInCode } from '../api/client'
import type { ConsentView, LlmOverview, MyData, Receipt } from '../api/types'
import {
  browserRecognitionAvailable,
  setSpeechEngine,
  speechEngine,
  type SpeechEngine,
} from '../voice/speech'
import { canSpeak, setVoiceKind, speakReplies, voiceKind, type VoiceKind } from '../voice/tts'
import { maskedKey, saveWakeSetup, WAKE_LABEL, wakeSetup } from '../voice/wake'

type Tab = 'privacy' | 'voice' | 'ai' | 'data' | 'terminal'

function message(e: unknown): string {
  return e instanceof ApiError || e instanceof Error ? e.message : String(e)
}

/** Privacy switches (docs/plan/14): each one stops its processing as soon as it's off. */
function Privacy() {
  const [view, setView] = useState<ConsentView | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.consent().then(setView, (e: unknown) => {
      setError(message(e))
    })
  }, [])

  const toggle = async (id: string, granted: boolean) => {
    const before = view
    // Show the change at once; the server's answer confirms it, or it's put back.
    setView((v) =>
      v ? { ...v, switches: v.switches.map((s) => (s.id === id ? { ...s, granted } : s)) } : v,
    )
    try {
      setView(await api.setConsent(id, granted))
      setError(null)
    } catch (e) {
      setView(before)
      setError(message(e))
    }
  }

  return (
    <div data-testid="privacy">
      {view && (
        <ul className="switches">
          {view.switches.map((s) => (
            <li key={s.id}>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={s.granted}
                  disabled={s.required}
                  onChange={(e) => void toggle(s.id, e.target.checked)}
                />
                <span>
                  <strong>{s.title}</strong>
                  {s.required && <span className="muted"> (needed)</span>}
                  <br />
                  <span className="muted">{s.plain}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      {view && <p className="muted">Notice version {view.version}.</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  )
}

/** Bring your own AI key (UW22). Before anything goes to a cloud provider, the user sees which
 * provider it is and where it processes data, and turns Cloud AI on. */
function Provider({ onChange }: { onChange: () => void }) {
  const [overview, setOverview] = useState<LlmOverview | null>(null)
  const [cloudOn, setCloudOn] = useState(false)
  const [adding, setAdding] = useState<string | null>(null)
  const [key, setKey] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const apply = useCallback(([llm, consent]: [LlmOverview, ConsentView]) => {
    setOverview(llm)
    setCloudOn(consent.switches.some((s) => s.id === 'cloud_ai' && s.granted))
  }, [])

  const load = useCallback(() => Promise.all([api.llm(), api.consent()]).then(apply), [apply])

  useEffect(() => {
    Promise.all([api.llm(), api.consent()]).then(apply, (e: unknown) => {
      setError(message(e))
    })
  }, [apply])

  const run = async (work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
      await load()
      onChange()
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  if (!overview) return error ? <p role="alert">{error}</p> : <p className="muted">Loading…</p>
  const selection = overview.selection
  const provider = (id: string) => overview.providers.find((p) => p.id === id)
  const adder = adding ? provider(adding) : undefined
  const keyFor = (id: string) => overview.credentials.find((c) => c.provider === id)

  return (
    <div data-testid="ai-provider">
      <p>
        {selection.mode === 'hosted' && cloudOn ? (
          <>
            Using <strong>{provider(selection.provider)?.name ?? selection.provider}</strong> (
            {selection.model}).
          </>
        ) : (
          <>
            <span className="badge" data-testid="local-badge">
              Local mode
            </span>{' '}
            Najma uses the model on this server; nothing leaves it.
          </>
        )}
      </p>
      {note && <p role="status">{note}</p>}
      {!overview.keys_enabled && (
        <p className="muted">This server can&apos;t store keys (no master key is set).</p>
      )}
      <ul className="providers">
        {overview.providers
          .filter((p) => p.needs_key)
          .map((p) => {
            const saved = keyFor(p.id)
            return (
              <li key={p.id}>
                <strong>{p.name}</strong>{' '}
                <span className="muted">· processes data in {p.hosting}</span>
                <div className="flex gap-2">
                  {saved ? (
                    <>
                      <code>••••{saved.key_last4}</code>
                      {saved.status !== 'ok' && <span className="muted">({saved.status})</span>}
                      {!(selection.mode === 'hosted' && selection.provider === p.id) && (
                        <button
                          type="button"
                          disabled={busy || !cloudOn}
                          onClick={() =>
                            void run(async () => {
                              await api.select({
                                mode: 'hosted',
                                provider: p.id,
                                model: p.default_model,
                              })
                            })
                          }
                        >
                          Use
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            await api.removeKey(p.id)
                            setNote(
                              `Key removed. ${selection.provider === p.id ? 'Back to local mode.' : ''}`,
                            )
                          })
                        }
                      >
                        Remove key
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      disabled={busy || !overview.keys_enabled}
                      onClick={() => {
                        setAdding(p.id)
                        setKey('')
                        setModels([])
                        setNote(null)
                      }}
                    >
                      Add key
                    </button>
                  )}
                </div>
              </li>
            )
          })}
      </ul>
      {selection.mode === 'hosted' && (
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await api.select({ mode: 'local', provider: 'ollama', model: 'local' })
            })
          }
        >
          Use the local model
        </button>
      )}

      {adder && !cloudOn && (
        <div
          className="confirm"
          role="dialog"
          aria-label="Turn on Cloud AI"
          data-testid="cloud-consent"
        >
          <p>
            To use {adder.name}, Najma will send short, de-identified summaries (no name, no raw
            answers) to {adder.name}, which processes data in {adder.hosting}. You can turn this off
            at any time.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className="primary"
              onClick={() =>
                void run(async () => {
                  await api.setConsent('cloud_ai', true)
                })
              }
            >
              Turn on Cloud AI
            </button>
            <button
              type="button"
              onClick={() => {
                setAdding(null)
              }}
            >
              Not now
            </button>
          </div>
        </div>
      )}

      {adder && cloudOn && (
        <form
          className="confirm"
          aria-label={`Key for ${adder.name}`}
          onSubmit={(e) => {
            e.preventDefault()
            void run(async () => {
              const saved = await api.saveKey(adder.id, key)
              setKey('')
              setModels(saved.models)
              setAdding(null)
              setNote(`Key works. Using ${adder.name}.`)
            })
          }}
        >
          <label htmlFor="api-key">
            {adder.name} API key
            {adder.console_url && (
              <>
                {' '}
                <a href={adder.console_url} target="_blank" rel="noreferrer">
                  (get one)
                </a>
              </>
            )}
          </label>
          <input
            id="api-key"
            type="password"
            autoComplete="off"
            value={key}
            onChange={(e) => {
              setKey(e.target.value)
            }}
          />
          <div className="flex gap-2">
            <button type="submit" className="primary" disabled={busy || key.trim().length < 8}>
              {busy ? 'Checking…' : 'Check and save'}
            </button>
            <button
              type="button"
              onClick={() => {
                setAdding(null)
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {models.length > 1 && selection.mode === 'hosted' && (
        <label className="block">
          Model{' '}
          <select
            value={selection.model}
            onChange={(e) =>
              void run(async () => {
                await api.select({
                  mode: 'hosted',
                  provider: selection.provider,
                  model: e.target.value,
                })
              })
            }
          >
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  )
}

/** See, edit, export and delete (UW14). */
function Data({ onDeleted }: { onDeleted: (receipt: Receipt) => void }) {
  const [data, setData] = useState<MyData | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.myData().then(setData, (e: unknown) => {
      setError(message(e))
    })
  }, [])

  useEffect(load, [load])

  const forget = async (work: () => Promise<void>) => {
    try {
      await work()
      load()
    } catch (e) {
      setError(message(e))
    }
  }

  return (
    <div data-testid="my-data">
      <h3>What Najma keeps about you</h3>
      {data && data.core.length === 0 && data.memories.length === 0 && (
        <p className="muted">Nothing yet.</p>
      )}
      {data && data.core.length > 0 && (
        <>
          <p className="muted">Your short profile (core.md)</p>
          <ul className="lines">
            {data.core.map((line) => (
              <li key={line}>
                {line}{' '}
                <button
                  type="button"
                  className="link"
                  onClick={() => void forget(() => api.forgetCoreLine(line))}
                >
                  Forget
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {data && data.life_context.length > 0 && (
        <>
          <p className="muted">What you told Najma about your days</p>
          <ul className="lines">
            {data.life_context.map((c) => (
              <li key={c.context_id}>
                {c.label}, {new Date(c.start).toLocaleDateString('en-GB')}{' '}
                <button
                  type="button"
                  className="link"
                  onClick={() => void forget(() => api.forgetLifeContext(c.context_id))}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {data && data.memories.length > 0 && (
        <>
          <p className="muted">Memories</p>
          <ul className="lines">
            {data.memories.map((m) => (
              <li key={m.id}>
                {m.text}{' '}
                <button
                  type="button"
                  className="link"
                  onClick={() => void forget(() => api.forgetMemory(m.collection, m.id))}
                >
                  Forget
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {data && !data.memory_available && (
        <p className="muted">Memories can&apos;t be shown right now.</p>
      )}

      <h3>Take it with you</h3>
      <button type="button" onClick={() => void forget(() => api.exportData())}>
        Export my data
      </button>

      <h3>Delete everything</h3>
      {!confirming ? (
        <button
          type="button"
          onClick={() => {
            setConfirming(true)
          }}
        >
          Delete everything
        </button>
      ) : (
        <div
          className="confirm"
          role="dialog"
          aria-label="Delete everything"
          data-testid="delete-confirm"
        >
          <p>
            This deletes your results, profile, memories, notes and keys from Najma, for good. It
            can&apos;t be undone.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className="danger"
              onClick={() =>
                void api.deleteEverything().then(onDeleted, (e: unknown) => {
                  setError(message(e))
                })
              }
            >
              Yes, delete everything
            </button>
            <button
              type="button"
              onClick={() => {
                setConfirming(false)
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  )
}

/** "Hey Najma" (docs/plan/12): the person's own Picovoice AccessKey and keyword file. Both stay
 * in this browser and are never sent to Najma's server; only the last 4 characters are shown. */
function WakeWord() {
  const [saved, setSaved] = useState(wakeSetup)
  const [key, setKey] = useState('')
  const [keyword, setKeyword] = useState<string | null>(null)
  if (saved)
    return (
      <p>
        On, with key <code>{maskedKey(saved.accessKey)}</code>.{' '}
        <button
          type="button"
          onClick={() => {
            saveWakeSetup(null)
            setSaved(null)
          }}
        >
          Turn off and forget the key
        </button>
      </p>
    )
  return (
    <form
      aria-label="Wake word"
      onSubmit={(e) => {
        e.preventDefault()
        if (!keyword) return
        const setup = { accessKey: key.trim(), keyword }
        saveWakeSetup(setup)
        setSaved(setup)
        setKey('')
      }}
    >
      <p className="muted">
        Off. To say &ldquo;{WAKE_LABEL}&rdquo; instead of tapping, add your own Picovoice AccessKey
        and a &ldquo;{WAKE_LABEL}&rdquo; keyword file for Web, both from{' '}
        <a href="https://console.picovoice.ai/" target="_blank" rel="noreferrer">
          the Picovoice Console
        </a>
        . The wake word is heard on this device only; Picovoice checks the key, and Najma&apos;s
        server never sees it.
      </p>
      <label htmlFor="wake-key">Picovoice AccessKey</label>
      <input
        id="wake-key"
        type="password"
        autoComplete="off"
        value={key}
        onChange={(e) => {
          setKey(e.target.value)
        }}
      />
      <label htmlFor="wake-file">Keyword file (.ppn, Web)</label>
      <input
        id="wake-file"
        type="file"
        accept=".ppn"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (!file) return
          void file.arrayBuffer().then((bytes) => {
            setKeyword(btoa(String.fromCharCode(...new Uint8Array(bytes))))
          })
        }}
      />
      <button
        type="submit"
        className="primary"
        disabled={key.trim().length < 8 || keyword === null}
      >
        Turn on the wake word
      </button>
    </form>
  )
}

/** How Najma listens and speaks (docs/plan/12). */
function Voice({ onChange }: { onChange: (speak: boolean) => void }) {
  const [engine, setEngine] = useState<SpeechEngine>(speechEngine)
  const [speakOn, setSpeakOn] = useState(speakReplies)
  const [kind, setKind] = useState<VoiceKind>(voiceKind)
  const pickKind = (next: VoiceKind) => {
    setVoiceKind(next)
    setKind(next)
  }
  return (
    <div data-testid="voice-settings">
      <h3>Listening</h3>
      <ul className="switches">
        <li>
          <label className="switch">
            <input
              type="radio"
              name="engine"
              checked={engine === 'browser'}
              disabled={!browserRecognitionAvailable()}
              onChange={() => {
                setSpeechEngine('browser')
                setEngine('browser')
              }}
            />
            <span>
              <strong>Your browser</strong>
              <br />
              <span className="muted">
                Fast. Chrome sends the audio to Google to turn it into text.
                {!browserRecognitionAvailable() && ' Not available in this browser.'}
              </span>
            </span>
          </label>
        </li>
        <li>
          <label className="switch">
            <input
              type="radio"
              name="engine"
              checked={engine === 'private'}
              onChange={() => {
                setSpeechEngine('private')
                setEngine('private')
              }}
            />
            <span>
              <strong>Private</strong>
              <br />
              <span className="muted">
                Turned into text on Najma&apos;s server; the audio is not kept. English only for
                now.
              </span>
            </span>
          </label>
        </li>
        <li>
          <label className="switch">
            <input
              type="radio"
              name="engine"
              checked={engine === 'device'}
              onChange={() => {
                setSpeechEngine('device')
                setEngine('device')
              }}
            />
            <span>
              <strong>Private, on this device</strong>
              <br />
              <span className="muted">
                Turned into text in this browser; the audio never leaves your device. A one-time
                download of about 80 MB, and slower on older computers. English only for now.
              </span>
            </span>
          </label>
        </li>
      </ul>
      <h3>Wake word</h3>
      <WakeWord />
      <h3>Speaking</h3>
      <label className="switch">
        <input
          type="checkbox"
          checked={speakOn}
          disabled={!canSpeak()}
          onChange={(e) => {
            setSpeakOn(e.target.checked)
            onChange(e.target.checked)
          }}
        />
        <span>
          <strong>Speak Najma&apos;s replies</strong>
          <br />
          <span className="muted">
            In your coach&apos;s voice, and Najma reads game instructions out loud. Everything
            spoken is also shown as text.
          </span>
        </span>
      </label>
      <ul className="switches">
        <li>
          <label className="switch">
            <input
              type="radio"
              name="voice-kind"
              checked={kind === 'browser'}
              onChange={() => {
                pickKind('browser')
              }}
            />
            <span>
              <strong>Your browser&apos;s voices</strong>
              <br />
              <span className="muted">Ready at once; they sound different on each device.</span>
            </span>
          </label>
        </li>
        <li>
          <label className="switch">
            <input
              type="radio"
              name="voice-kind"
              checked={kind === 'natural'}
              onChange={() => {
                pickKind('natural')
              }}
            />
            <span>
              <strong>Natural voices</strong>
              <br />
              <span className="muted">
                A voice for each coach, made in this browser (Kokoro). A one-time download of about
                90 MB.
              </span>
            </span>
          </label>
        </li>
      </ul>
    </div>
  )
}

/** Najma in a terminal (UW19): the `najma` CLI signs in with this browser's code. */
function Terminal() {
  const [code, setCode] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  return (
    <div data-testid="terminal-settings">
      <h3>Use Najma in a terminal</h3>
      <p className="muted">
        The <code>najma</code> command chats with Najma, plays the text games and shows your profile
        and goals, from the same data as this app. Run <code>najma login</code> and paste your
        sign-in code.
      </p>
      {code === null ? (
        <button
          type="button"
          onClick={() => {
            setCode(signInCode() ?? '')
          }}
        >
          Show sign-in code
        </button>
      ) : (
        <div className="sign-in-code">
          <code data-testid="sign-in-code">{code}</code>
          <button
            type="button"
            onClick={() => {
              void navigator.clipboard.writeText(code).then(() => {
                setCopied(true)
              })
            }}
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button
            type="button"
            onClick={() => {
              setCode(null)
              setCopied(false)
            }}
          >
            Hide
          </button>
        </div>
      )}
      <p className="muted">
        Anyone with this code can use your Najma account, so keep it to yourself. Deleting your data
        in Memory &amp; data turns it off.
      </p>
    </div>
  )
}

export function Settings({
  onLlmChange,
  onVoiceChange,
  onDeleted,
}: {
  onLlmChange: () => void
  onVoiceChange: (speak: boolean) => void
  onDeleted: (receipt: Receipt) => void
}) {
  const [tab, setTab] = useState<Tab>('privacy')
  const tabs: [Tab, string][] = [
    ['privacy', 'Privacy'],
    ['voice', 'Voice'],
    ['ai', 'AI provider'],
    ['data', 'Memory & data'],
    ['terminal', 'Terminal'],
  ]
  return (
    <section className="card settings" data-testid="settings">
      <h2>Settings</h2>
      <div className="tabs" role="tablist">
        {tabs.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => {
              setTab(id)
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'privacy' && <Privacy />}
      {tab === 'voice' && <Voice onChange={onVoiceChange} />}
      {tab === 'ai' && <Provider onChange={onLlmChange} />}
      {tab === 'data' && <Data onDeleted={onDeleted} />}
      {tab === 'terminal' && <Terminal />}
    </section>
  )
}
