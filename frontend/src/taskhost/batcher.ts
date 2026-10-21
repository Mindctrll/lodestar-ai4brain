import type { TrialEvent } from '../api/types'

type Send = (trials: TrialEvent[]) => Promise<unknown>

/** Streams trials to POST /events in small batches; failed batches are retried. */
export class TrialBatcher {
  private queue: TrialEvent[] = []
  private timer: ReturnType<typeof setInterval> | null = null
  private inFlight: Promise<void> = Promise.resolve()

  constructor(
    private readonly send: Send,
    private readonly maxBatch = 10,
    intervalMs = 2000,
    private readonly retries = 3,
  ) {
    this.timer = setInterval(() => void this.flush(), intervalMs)
  }

  add(trial: TrialEvent): void {
    this.queue.push(trial)
    if (this.queue.length >= this.maxBatch) void this.flush()
  }

  flush(): Promise<void> {
    if (this.queue.length === 0) return this.inFlight
    const batch = this.queue
    this.queue = []
    this.inFlight = this.inFlight.then(() => this.sendWithRetry(batch))
    return this.inFlight
  }

  private async sendWithRetry(batch: TrialEvent[]): Promise<void> {
    for (let attempt = 0; attempt <= this.retries; attempt++) {
      try {
        await this.send(batch)
        return
      } catch {
        if (attempt === this.retries) {
          this.queue = [...batch, ...this.queue] // keep them for the next flush
          return
        }
        await new Promise((resolve) => setTimeout(resolve, 200 * 2 ** attempt))
      }
    }
  }

  async close(): Promise<void> {
    if (this.timer !== null) clearInterval(this.timer)
    this.timer = null
    await this.flush()
  }

  get pending(): number {
    return this.queue.length
  }
}
