import { expect, test } from '@playwright/test'

import { expectWellFormed, playCurrentGame, prepare, startSession } from './helpers'

// WP3.1: Callback replays the words of this session's Market List as a delayed recall.
test('Callback asks for the Market List words from earlier in the session', async ({ page }) => {
  const sent = await prepare(page)
  await startSession(page, 'play Market List')
  await playCurrentGame(page)
  await expect(page.getByTestId('after-game')).toBeVisible({ timeout: 60_000 })
  const listed = sent
    .filter((t) => t.game_id === 'market_list' && !t.practice)
    .map((t) => String(t.stimulus['word']))

  await page.getByTestId('say').fill('play Callback')
  await page.getByRole('button', { name: 'Send' }).click()
  // The request is honoured by the next pick.
  await expect(page.getByTestId('chat')).toContainText('play Callback')
  await page.getByRole('button', { name: 'Next game' }).click()
  await expect(page.getByRole('heading', { name: 'Callback' })).toBeVisible({ timeout: 60_000 })
  await playCurrentGame(page, { picked: true })
  const recalled = sent.filter((t) => t.game_id === 'callback')
  expectWellFormed(recalled, 'callback')
  expect(recalled.map((t) => String(t.stimulus['word'])).sort()).toEqual(listed.sort())
  expect(recalled.every((t) => t.correct === true)).toBe(true)
})
