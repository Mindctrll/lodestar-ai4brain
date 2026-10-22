import { readFileSync } from 'node:fs'

import { expect, test } from '@playwright/test'

import { playCurrentGame } from './helpers'

// Wave 2 gate (docs/plan/16): consent → onboarding → 3 games → coach with why cards → dashboard
// updates → export → delete, as one person would do it.
test('wave 2 gate: a whole first week in one go', async ({ page }) => {
  test.setTimeout(300_000)
  await page.addInitScript(() => {
    ;(window as unknown as { __LODESTAR_E2E__: boolean }).__LODESTAR_E2E__ = true
  })
  await page.goto('/')

  // Consent and coach (UW1).
  await page.getByRole('button', { name: 'Get started' }).click()
  await page.getByRole('button', { name: "I'm 18 or older" }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('radio', { name: /Willow/ }).check()
  await page.getByRole('button', { name: "Let's start" }).click()

  // Onboarding: the warm-up battery, three games, each explained before it starts.
  await page.getByRole('button', { name: 'Start a session' }).click()
  for (let game = 0; game < 3; game++) {
    const suggestion = game === 0 ? page.getByTestId('suggestion') : page.getByTestId('after-game')
    await expect(suggestion).toBeVisible({ timeout: 60_000 })
    if (game === 0) {
      await expect(page.locator('.reason')).toContainText('Warm-up game 1')
      await page.getByRole('button', { name: 'Why?' }).click()
      await expect(page.getByTestId('why-card')).toContainText('Why this choice')
      await page.getByTestId('why-card').getByRole('button', { name: 'Close' }).click()
    }
    await playCurrentGame(page)
    // The coach answers from facts; every fact is a chip next to the sentence that uses it.
    // Fact lines sit behind \"How I worked this out\".
    await page.getByTestId('coach').getByText('How I worked this out').click({ timeout: 60_000 })
    await expect(page.getByTestId('coach').locator('.cite').first()).toBeVisible({
      timeout: 60_000,
    })
  }

  // The dashboard has learned something, with ranges.
  await page.getByRole('button', { name: 'Brain Twin' }).click()
  const measured = page.getByTestId('night-sky').locator('[data-dim]:not([data-blur="none"])')
  await expect(measured.first()).toBeVisible()
  expect(await measured.count()).toBeGreaterThanOrEqual(3)
  await expect(page.getByLabel(/Radar of your skills/)).toBeVisible()

  // Export, then delete with a receipt.
  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('tab', { name: 'Memory & data' }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export my data' }).click()
  const file = await download
  const data = JSON.parse(readFileSync(await file.path(), 'utf8')) as {
    tables: Record<string, unknown[]>
  }
  expect((data.tables['twin.rounds'] ?? []).length).toBeGreaterThanOrEqual(3)
  await page.getByRole('button', { name: 'Delete everything' }).click()
  await page
    .getByTestId('delete-confirm')
    .getByRole('button', { name: 'Yes, delete everything' })
    .click()
  await expect(page.getByTestId('receipt')).toContainText(
    /Deleted \d[\d,]* events, [3-9]\d* rounds/,
  )
})
