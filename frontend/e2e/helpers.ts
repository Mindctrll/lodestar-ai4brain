import { expect, type Page, type Request } from '@playwright/test'

export interface SentTrial {
  round_id: string
  game_id: string
  trial_index: number
  practice: boolean
  correct: boolean | null
  rt_ms: number | null
  stimulus: Record<string, unknown>
}

/** Turn on the test flag (stimuli expose their expected answer) and record every trial sent. */
export async function prepare(page: Page): Promise<SentTrial[]> {
  await page.addInitScript(() => {
    ;(window as unknown as { __NAJMA_E2E__: boolean }).__NAJMA_E2E__ = true
  })
  const sent: SentTrial[] = []
  page.on('request', (request: Request) => {
    if (request.method() === 'POST' && request.url().endsWith('/api/events')) {
      const body = request.postDataJSON() as { trials: SentTrial[] }
      sent.push(...body.trials)
    }
  })
  return sent
}

/** Start a session asking for something, as if the user said it. */
export async function startSession(page: Page, ask: string): Promise<void> {
  await page.goto(`/?ask=${encodeURIComponent(ask)}`)
  await page.getByRole('button', { name: 'Start a session' }).click()
  await expect(page.getByTestId('suggestion')).toBeVisible({ timeout: 30_000 })
}

/** Play the current game by reading each trial's expected answer and giving it. */
export async function playCurrentGame(page: Page): Promise<void> {
  await page.getByRole('button', { name: /Let's go|Next game/ }).click()
  await page.getByRole('button', { name: 'Start' }).click()
  const after = page.getByTestId('after-game')
  let last = -1
  for (;;) {
    if (await after.isVisible()) return
    // The next trial we haven't answered yet, once it is listening for an answer.
    const stage = page.locator(
      `[data-testid="stage"][data-answer]:not([data-trial="${String(last)}"])`,
    )
    try {
      await stage.waitFor({ timeout: 3_000 })
    } catch {
      continue
    }
    const [answer, trial] = await Promise.all([
      stage.getAttribute('data-answer'),
      stage.getAttribute('data-trial'),
    ])
    // Answer at a human pace: faster than ~200 ms is treated as impossible and isn't counted.
    if (answer !== 'none') await page.waitForTimeout(250 + Math.random() * 150)
    if (answer === 'match' || answer === ' ') await page.keyboard.press('Space')
    else if (answer && answer !== 'none') await page.keyboard.press(answer)
    last = Number(trial)
  }
}

export function expectWellFormed(trials: SentTrial[], gameId: string): void {
  expect(trials.length).toBeGreaterThan(5)
  const rounds = new Set(trials.map((t) => t.round_id))
  expect(rounds.size).toBe(1)
  const indexes = trials.map((t) => t.trial_index)
  expect(new Set(indexes).size).toBe(indexes.length)
  for (const t of trials) {
    expect(t.game_id).toBe(gameId)
    expect(typeof t.practice).toBe('boolean')
    expect(t.stimulus).toBeTruthy()
  }
}
