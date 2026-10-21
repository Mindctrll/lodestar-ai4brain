import { API_BASE } from './client'
import type { AgentEvent, RoundResult } from './types'

type Listener = (event: AgentEvent) => void

/** The live agent stream for one session (WebSocket; the first frame authenticates). */
export class SessionSocket {
  private socket: WebSocket | null = null
  private readonly listeners = new Set<Listener>()
  private ready: Promise<void> | null = null

  constructor(
    readonly sessionId: string,
    private readonly token: string,
  ) {}

  private url(): string {
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${scheme}://${window.location.host}${API_BASE}/sessions/${this.sessionId}/stream`
  }

  connect(): Promise<void> {
    if (this.ready) return this.ready
    this.ready = new Promise((resolve, reject) => {
      const socket = new WebSocket(this.url())
      this.socket = socket
      socket.addEventListener('open', () => {
        socket.send(JSON.stringify({ type: 'auth', token: this.token }))
        resolve()
      })
      socket.addEventListener('error', () => {
        reject(new Error('Could not reach Najma'))
      })
      socket.addEventListener('message', (message: MessageEvent<string>) => {
        const event = JSON.parse(message.data) as AgentEvent
        for (const listener of this.listeners) listener(event)
      })
    })
    return this.ready
  }

  onEvent(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  async resume(result: RoundResult): Promise<void> {
    await this.connect()
    this.socket?.send(JSON.stringify({ type: 'resume', value: result }))
  }

  /** Answer a "Shall I…?" question from Najma. */
  async confirm(confirmed: boolean): Promise<void> {
    await this.connect()
    this.socket?.send(JSON.stringify({ type: 'resume', value: { confirmed } }))
  }

  /** Ask Najma for the next game without saying anything. */
  async next(): Promise<void> {
    await this.connect()
    this.socket?.send(JSON.stringify({ type: 'start' }))
  }

  async say(text: string): Promise<void> {
    await this.connect()
    this.socket?.send(JSON.stringify({ type: 'message', text }))
  }

  close(): void {
    this.socket?.close()
    this.socket = null
    this.ready = null
  }
}
