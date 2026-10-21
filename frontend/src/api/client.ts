import type { AgentEvent, Registry, TrialEvent, TwinView } from './types'

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

/** Make sure this browser has a user and a token (WP2.8 adds consent and the age check). */
export async function ensureUser(): Promise<string> {
  const existing = memoryToken ?? getToken()
  if (existing) return existing
  const created = await request<{ user_id: string; token: string }>('/users', { method: 'POST' })
  memoryToken = created.token
  setToken(created.token)
  return created.token
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
  pending: (sessionId: string) =>
    request<{ pending: AgentEvent | null }>(`/sessions/${sessionId}/pending`),
  sendTrials: (trials: TrialEvent[]) =>
    request<{ accepted: number; duplicates: number }>('/events', {
      method: 'POST',
      body: JSON.stringify({ trials }),
    }),
}
