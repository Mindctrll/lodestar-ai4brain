import { expect, test } from '@playwright/test'

import { prepare } from './helpers'

// WP2.11: talk to Lodestar before playing. A change (noting a bad night) waits for a yes; a
// question about a pick cites it, and the citation opens the "why" card (UW7, UW9).
test('tell Lodestar about a bad night, then ask why it picked a game', async ({ page }) => {
  await prepare(page)
  await page.goto('/')
  const say = page.getByTestId('say')
  await say.fill('I slept like 4 hours.')
  await page.getByRole('button', { name: 'Send' }).click()

  const confirm = page.getByTestId('confirm')
  await expect(confirm).toContainText('slept badly', { timeout: 30_000 })
  await confirm.getByRole('button', { name: 'Yes' }).click()
  await expect(page.getByTestId('chat')).toContainText('Thanks for telling me.', {
    timeout: 30_000,
  })

  await page.getByRole('button', { name: 'Play a game' }).click()
  const suggestion = page.getByTestId('suggestion')
  await expect(suggestion).toBeVisible({ timeout: 30_000 })
  const title = await suggestion.getByRole('heading').textContent()

  await say.fill('why this game?')
  await page.getByRole('button', { name: 'Send' }).click()
  const chip = page.getByRole('button', { name: 'Why? (D1)' })
  await expect(chip).toBeVisible({ timeout: 60_000 })
  await chip.click()
  const card = page.getByTestId('why-card')
  await expect(card).toContainText('Top options')
  await card.getByRole('button', { name: 'Close' }).click()
  // The question didn't replace the game that was waiting.
  await expect(suggestion.getByRole('heading')).toHaveText(title ?? '')
})
