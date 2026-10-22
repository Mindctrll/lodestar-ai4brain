import { expect, test } from '@playwright/test'

import { playCurrentGame, prepare } from './helpers'

// UW19: `lodestar login` takes the code from Settings > Terminal, and a game the terminal can't
// play is handed to the browser (`?session=<id>`), which picks up the same session.
test('uw19 terminal: the sign-in code, and a game handed over from the CLI', async ({ page }) => {
  await prepare(page)
  await page.goto('/')
  const token = await page.evaluate(() => localStorage.getItem('lodestar.token'))

  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('tab', { name: 'Terminal' }).click()
  await expect(page.getByTestId('sign-in-code')).toHaveCount(0)
  await page.getByRole('button', { name: 'Show sign-in code' }).click()
  await expect(page.getByTestId('sign-in-code')).toHaveText(token ?? 'missing')

  // What the CLI's MCP server does when the user asks for a game with no text version.
  const started = await page.request.post('/api/sessions', {
    headers: { Authorization: `Bearer ${token ?? ''}` },
    data: { trigger: 'cli', message: 'play Ink Clash' },
  })
  const { session_id: sessionId } = (await started.json()) as { session_id: string }
  await page.goto(`/?session=${sessionId}`)
  await expect(page.getByTestId('resume')).toContainText('Ink Clash')
  expect(page.url()).not.toContain('session=')
  await page.getByRole('button', { name: 'Resume' }).click()
  await playCurrentGame(page)
  // Fact lines sit behind \"How I worked this out\".
  await page.getByTestId('coach').getByText('How I worked this out').click({ timeout: 60_000 })
  await expect(page.getByTestId('coach').locator('.cite').first()).toBeVisible({ timeout: 60_000 })
})
