import { expect, test } from '@playwright/test'

import { playCurrentGame, prepare, startSession } from './helpers'

// UW6: the laptop closes mid-game; reopening offers to resume, and the round is scored once.
test('uw6_resume: a refresh mid-game offers to resume and scores the round once', async ({
  page,
}) => {
  await prepare(page)
  await startSession(page, 'play Ink Clash')
  await page.getByRole('button', { name: "Let's go" }).click()
  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page.getByTestId('stage')).toBeVisible()
  await page.reload()

  await expect(page.getByTestId('resume')).toContainText('Ink Clash')
  await page.getByRole('button', { name: 'Resume' }).click()
  await playCurrentGame(page)
  await expect(page.getByTestId('coach')).toContainText('[F', { timeout: 60_000 })
})
