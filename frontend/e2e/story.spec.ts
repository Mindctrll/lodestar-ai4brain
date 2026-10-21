import { expect, test } from '@playwright/test'

import { playCurrentGame, prepare } from './helpers'

const CHAPTERS = [
  { game: 'Twins', title: 'The two notes' },
  { game: 'Seen It?', title: 'The witness' },
  { game: 'Logic Lock', title: 'The locked box' },
]

// WP3.8: the Detective story serves its chapters in order, each one a normal game, then ends.
test('plays the Detective story from the first chapter to the ending', async ({ page }) => {
  test.setTimeout(600_000)
  const sent = await prepare(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Detective story' }).click()
  await expect(page.getByTestId('suggestion')).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.reason')).toContainText('A brass lamp has gone missing')

  for (const [i, chapter] of CHAPTERS.entries()) {
    if (i === 0) await page.getByRole('button', { name: "Let's go" }).click()
    else await page.getByRole('button', { name: 'Next game' }).click()
    await expect(page.getByRole('heading', { name: chapter.game })).toBeVisible({
      timeout: 60_000,
    })
    await expect(page.locator('.game-frame__reason')).toContainText(
      `chapter ${String(i + 1)} of 3: ${chapter.title}`,
    )
    await playCurrentGame(page, { picked: true })
    await expect(page.getByTestId('coach')).not.toBeEmpty({ timeout: 60_000 })
  }
  await expect(page.getByTestId('coach')).toContainText('Case closed!', { timeout: 60_000 })
  const games = [...new Set(sent.filter((t) => !t.practice).map((t) => t.game_id))]
  expect(games).toEqual(['twins', 'seen_it', 'logic_lock'])
})
