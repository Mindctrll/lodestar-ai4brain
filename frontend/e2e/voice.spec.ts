import path from 'node:path'

import { expect, test, type Request } from '@playwright/test'

import { prepare } from './helpers'

// WP2.10 "Done when" and UW4: a recorded request, spoken into Chromium's fake microphone, goes
// through tap-to-talk and private speech to text, and starts the right game with its theme.
const FIXTURE = path.resolve(
  import.meta.dirname,
  '..',
  '..',
  'tests',
  'fixtures',
  'voice',
  'give_me_a_memory_game_about_football.wav',
)

test.use({
  permissions: ['microphone'],
  launchOptions: {
    args: [
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${FIXTURE}`,
    ],
  },
})

test('uw4 voice request: "give me a memory game about football"', async ({ page }) => {
  await prepare(page)
  await page.addInitScript(() => {
    localStorage.setItem('lodestar.voice.engine', 'private')
  })
  const started: Request[] = []
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().endsWith('/api/sessions')) started.push(r)
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Tap to talk (Alt+V)' }).click()
  // First time: the microphone switch is asked for in place.
  await page
    .getByRole('dialog', { name: 'Turn on the microphone' })
    .getByRole('button', {
      name: 'Turn on the microphone',
    })
    .click()
  const listening = page.getByRole('button', { name: 'Listening. Tap to send' })
  await expect(listening).toBeVisible()
  await page.waitForTimeout(3300) // the phrase, then silence (the fake microphone loops the file)
  const session = page.waitForResponse((r) => r.url().endsWith('/api/sessions') && r.ok(), {
    timeout: 60_000,
  })
  await listening.click()
  await expect(page.getByTestId('voice-caption')).toHaveText(
    /give me a memory game about football/i,
    { timeout: 60_000 },
  )
  const body = (await (await session).json()) as {
    events: { kind: string; payload?: { spec?: { game_id: string; content: { theme: string } } } }[]
  }
  expect(started[0]?.postDataJSON()).toMatchObject({ trigger: 'voice' })
  const spec = body.events.find((e) => e.kind === 'interrupt')?.payload?.spec
  expect(spec?.game_id).toBe('market_list')
  expect(spec?.content.theme).toBe('football')
  await expect(page.getByTestId('suggestion')).toContainText('Market List')
  await expect(page.getByTestId('suggestion')).toContainText('Football memory, coming up')
})
