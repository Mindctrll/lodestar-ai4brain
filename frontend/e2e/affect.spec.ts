import { expect, test } from '@playwright/test'

import { playCurrentGame, prepare, startSession } from './helpers'

// WP2.9 (docs/plan/12): four misses in a row bring the "easier?" offer; after the round the user
// can tap a mood and tell Lodestar whether easing off was the right call. Both go to the event log.
test('a run of misses offers an easier round, then mood and "Was I right?"', async ({ page }) => {
  await prepare(page)
  const labels: unknown[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/api/affect/labels'))
      labels.push(request.postDataJSON())
  })
  await startSession(page, 'play Quick Draw')
  const offer = page.getByTestId('easier-offer')
  await playCurrentGame(page, { missScored: true, until: offer })
  await expect(offer).toBeVisible()
  await offer.getByRole('button', { name: 'Yes, easier' }).click()
  await expect(page.getByTestId('after-game')).toBeVisible({ timeout: 30_000 })

  await expect(page.getByRole('group', { name: 'Mood' })).toBeVisible({ timeout: 60_000 })
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/affect/labels'))
  await page.getByRole('button', { name: /Tough/ }).click()
  expect((await saved).status()).toBe(204)
  await expect(page.getByText('Was I right?')).toBeVisible()
  const answered = page.waitForResponse((r) => r.url().endsWith('/api/affect/labels'))
  await page.getByRole('button', { name: 'Yes', exact: true }).click()
  expect((await answered).status()).toBe(204)
  expect(labels).toEqual([
    expect.objectContaining({ kind: 'mood', value: 'tough' }),
    expect.objectContaining({ kind: 'was_i_right', value: 'yes' }),
  ])
})
