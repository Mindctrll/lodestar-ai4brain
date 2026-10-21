import type {
  AgentEvent,
  AcsView,
  ConsentView,
  Decision,
  ExperimentView,
  ForecastView,
  GoalView,
  KeySaved,
  LlmOverview,
  LlmSelection,
  MeView,
  MyData,
  Persona,
  ProgressView,
  Receipt,
  TraceRow,
  Registry,
  TrialEvent,
  TwinView,
} from './types'

const TOKEN_KEY = 'najma.token'
export const API_BASE = '/api'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // Private mode: the token lives only in memory for this page.
  }
}

let memoryToken: string | null = null

/** The code `najma login` asks for: this browser's sign-in token (UW19). */
export function signInCode(): string | null {
  return memoryToken ?? getToken()
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = memoryToken ?? getToken()
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // keep statusText
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** `?signin=<token>` (printed by `make seed`) signs this browser in as that user once, then the
 * token leaves the address bar. For the demo user; everyone else signs up through the first-visit
 * screens. */
export function adoptSignIn(): void {
  const url = new URL(window.location.href)
  const token = url.searchParams.get('signin')
  if (!token) return
  memoryToken = token
  setToken(token)
  url.searchParams.delete('signin')
  window.history.replaceState(null, '', url.toString())
}

export function hasUser(): boolean {
  return Boolean(memoryToken ?? getToken())
}

/** The token of the user who went through the first-visit screens. */
export function ensureUser(): Promise<string> {
  const existing = memoryToken ?? getToken()
  if (existing) return Promise.resolve(existing)
  return Promise.reject(new Error('Finish the first-visit screens first'))
}

/** Create the user once the age check, consent and coach are chosen (UW1). */
export async function signUp(choices: {
  consent: Record<string, boolean>
  persona: Persona
}): Promise<string> {
  let timezone: string | undefined
  try {
    timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  } catch {
    timezone = undefined
  }
  const created = await request<{ user_id: string; token: string }>('/users', {
    method: 'POST',
    body: JSON.stringify({ age_confirmed: true, timezone, ...choices }),
  })
  memoryToken = created.token
  setToken(created.token)
  return created.token
}

/** After "Delete everything": forget this browser's user. */
export function forgetUser(): void {
  memoryToken = null
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem('najma.session')
    localStorage.removeItem('najma.voice.baseline') // voice tone baseline (affect/voiceTone.ts)
  } catch {
    // nothing stored
  }
}

/** Download a response body as a file. */
async function download(path: string, filename: string): Promise<void> {
  const token = memoryToken ?? getToken()
  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) throw new ApiError(response.status, response.statusText)
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export interface SessionStart {
  session_id: string
  events: AgentEvent[]
}

export const api = {
  registry: () => request<Registry>('/registry'),
  twin: () => request<TwinView>('/twin'),
  startSession: (trigger: 'ui' | 'voice' = 'ui', message?: string) =>
    request<SessionStart>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ trigger, message: message ?? null }),
    }),
  label: (body: {
    session_id: string
    kind: 'mood' | 'was_i_right'
    value: string
    round_id?: string
    decision_id?: string
  }) => request<undefined>('/affect/labels', { method: 'POST', body: JSON.stringify(body) }),
  cues: (body: {
    session_id: string
    strain_cue: number | null
    voice_strain_cue: number | null
  }) => request<undefined>('/affect/cues', { method: 'POST', body: JSON.stringify(body) }),
  pending: (sessionId: string) =>
    request<{ pending: AgentEvent | null }>(`/sessions/${sessionId}/pending`),
  decision: (decisionId: string) => request<Decision>(`/decisions/${decisionId}`),
  consent: () => request<ConsentView>('/consent'),
  setConsent: (switchId: string, granted: boolean) =>
    request<ConsentView>(`/consent/${switchId}`, {
      method: 'PUT',
      body: JSON.stringify({ granted }),
    }),
  llm: () => request<LlmOverview>('/llm/providers'),
  saveKey: (provider: string, apiKey: string) =>
    request<KeySaved>(`/llm/credentials/${provider}`, {
      method: 'PUT',
      body: JSON.stringify({ api_key: apiKey }),
    }),
  removeKey: (provider: string) =>
    request<undefined>(`/llm/credentials/${provider}`, { method: 'DELETE' }),
  select: (selection: LlmSelection) =>
    request<LlmSelection>('/llm/selection', {
      method: 'PUT',
      body: JSON.stringify(selection),
    }),
  myData: () => request<MyData>('/me/data'),
  forgetCoreLine: (line: string) =>
    request<undefined>('/me/core/forget', { method: 'POST', body: JSON.stringify({ line }) }),
  forgetMemory: (collection: string, id: string) =>
    request<undefined>(`/me/memories/${collection}/${id}`, { method: 'DELETE' }),
  forgetLifeContext: (id: string) =>
    request<undefined>(`/me/life-context/${id}`, { method: 'DELETE' }),
  exportData: () => download('/me/export', 'najma-export.json'),
  deleteEverything: () => request<Receipt>('/me', { method: 'DELETE' }),
  goals: () => request<GoalView[]>('/goals'),
  progress: () => request<ProgressView>('/progress'),
  me: () => request<MeView>('/me'),
  experiments: () => request<ExperimentView[]>('/experiments'),
  cancelExperiment: (id: string) =>
    request<undefined>(`/experiments/${id}/cancel`, { method: 'POST' }),
  forecast: (sessions = 5) => request<ForecastView[]>(`/forecast?sessions=${String(sessions)}`),
  acs: () => request<AcsView>('/acs'),
  decisions: (limit = 20) => request<Decision[]>(`/me/decisions?limit=${String(limit)}`),
  trace: (sessionId: string) => request<TraceRow[]>(`/sessions/${sessionId}/trace`),
  sendTrials: (trials: TrialEvent[]) =>
    request<{ accepted: number; duplicates: number }>('/events', {
      method: 'POST',
      body: JSON.stringify({ trials }),
    }),
}
