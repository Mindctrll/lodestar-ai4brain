import { expect, type Locator, type Page, type Request } from '@playwright/test'

export interface SentTrial {
  round_id: string
  game_id: string
  trial_index: number
  practice: boolean
  correct: boolean | null
  rt_ms: number | null
  hint_level: number
  stimulus: Record<string, unknown>
  response: Record<string, unknown> | null
}

/** Turn on the test flag (stimuli expose their expected answer) and record every trial sent.
 * Unless `firstVisit` is set, a user who already went through the first-visit screens (18+,
 * default consent) is signed in. */
export async function prepare(
  page: Page,
  { firstVisit = false }: { firstVisit?: boolean } = {},
): Promise<SentTrial[]> {
  await page.addInitScript(() => {
    ;(window as unknown as { __NAJMA_E2E__: boolean }).__NAJMA_E2E__ = true
  })
  if (!firstVisit) {
    const created = await page.request.post('/api/users', { data: { age_confirmed: true } })
    const { token } = (await created.json()) as { token: string }
    await page.addInitScript((t: string) => {
      if (!localStorage.getItem('najma.token')) localStorage.setItem('najma.token', t)
    }, token)
  }
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

/** Perform one expected answer (see markAnswer in src/taskhost/plugin.ts). */
async function perform(page: Page, answer: string): Promise<void> {
  if (answer.includes(' >> ')) {
    // Several actions in order, e.g. ask Najma first, then type (Guide the Robot, Teach Me).
    for (const part of answer.split(' >> ')) await perform(page, part)
    return
  }
  const [kind, ...rest] = answer.split(':')
  const arg = rest.join(':')
  if (kind === 'none') return
  // Answer at a human pace: faster than ~200 ms is treated as impossible and isn't counted.
  await page.waitForTimeout(250 + Math.random() * 150)
  if (kind === 'key') await page.keyboard.press(arg)
  else if (kind === 'click') await page.getByTestId(arg).click()
  else if (kind === 'clicks') {
    for (const id of arg.split('|')) await page.getByTestId(id).click()
  } else if (kind === 'type') {
    await page.getByTestId('recall-input').fill(arg)
    await page.getByTestId('recall-done').click()
  } else if (kind === 'point') {
    const [id, fraction] = arg.split(':')
    const box = await page.getByTestId(id).boundingBox()
    if (!box) throw new Error(`no box for ${id}`)
    await page.mouse.click(box.x + box.width * Number(fraction), box.y + box.height / 2)
  }
}

export interface PlayOptions {
  /** Let every scored step run out instead of answering (practice is still answered). */
  missScored?: boolean
  /** Stop playing as soon as this shows up. */
  until?: Locator
  /** The game is already picked (its Start button is showing). */
  picked?: boolean
}

/** Play the current game by reading each step's expected answer and giving it. */
export async function playCurrentGame(page: Page, options: PlayOptions = {}): Promise<void> {
  if (!options.picked) await page.getByRole('button', { name: /Let's go|Next game/ }).click()
  await page.getByRole('button', { name: 'Start' }).click()
  const after = page.getByTestId('after-game')
  let last = ''
  for (;;) {
    if (await after.isVisible()) return
    if (options.until && (await options.until.isVisible())) return
    // The next step we haven't answered yet, once it is listening for an answer.
    const stage = page.locator(`[data-testid="stage"][data-answer]:not([data-trial="${last}"])`)
    try {
      await stage.waitFor({ timeout: 3_000 })
    } catch {
      continue
    }
    const [answer, trial, practice] = await Promise.all([
      stage.getAttribute('data-answer'),
      stage.getAttribute('data-trial'),
      stage.getAttribute('data-practice'),
    ])
    const miss = options.missScored === true && practice !== 'true'
    await perform(page, miss ? 'none' : (answer ?? 'none'))
    last = trial ?? ''
  }
}

export function expectWellFormed(trials: SentTrial[], gameId: string, minTrials = 4): void {
  expect(trials.length).toBeGreaterThanOrEqual(minTrials)
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
