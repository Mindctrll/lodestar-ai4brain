import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

import { expect, test, type Locator, type Page } from '@playwright/test'

import { playCurrentGame } from './helpers'

// The six stress cases in the real app, on Alex's seeded data. Each step leaves a screenshot in
// screenshots/stress-cases/ (make e2e writes them too).

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'screenshots', 'stress-cases')

function seededToken(): string {
  const out = execFileSync('uv', ['run', 'python', '-m', 'backend.db.seed', '--reset', '--token'], {
    cwd: ROOT,
    encoding: 'utf8',
  })
  const line = out.split('\n').find((l) => l.startsWith('TOKEN='))
  if (!line) throw new Error(`seed printed no token: ${out}`)
  return line.slice('TOKEN='.length)
}

async function shot(page: Page, name: string, target?: Locator): Promise<void> {
  await page.waitForTimeout(900) // let charts and animations settle
  const file = path.join(OUT, `${name}.png`)
  if (target) {
    await target.scrollIntoViewIfNeeded()
    await page.waitForTimeout(300)
  }
  await page.screenshot({ path: file })
}

async function say(page: Page, text: string): Promise<void> {
  await page.getByTestId('say').fill(text)
  await page.getByRole('button', { name: 'Send' }).click()
}

test('the six stress cases, with screenshots', async ({ page }) => {
  test.setTimeout(420_000)
  page.setDefaultTimeout(30_000)
  mkdirSync(OUT, { recursive: true })
  await page.setViewportSize({ width: 1440, height: 950 })
  await page.addInitScript(() => {
    ;(window as unknown as { __LODESTAR_E2E__: boolean }).__LODESTAR_E2E__ = true
  })
  await page.goto(`/?signin=${seededToken()}`)

  // Plateau: the popup, the map, the skill's own page with the highlighted curve.
  const toast = page.getByTestId('plateau-toast')
  await expect(toast).toBeVisible({ timeout: 30_000 })
  await expect(toast).toContainText('Sustained attention')
  await shot(page, '01-plateau-popup-on-home')
  await toast.getByRole('button', { name: 'See the curve' }).click()
  const note = page.getByTestId('plateau-note')
  await expect(note).toBeVisible()
  await shot(page, '02-plateau-on-skill-page', note)
  await page.getByRole('button', { name: /Back to the sky/ }).click()

  // Split profile: the map, the radar and the two-track plan.
  await expect(page.getByTestId('night-sky')).toBeVisible()
  await shot(page, '03-map-marks-plateau-and-split')
  const plan = page.getByTestId('split-plan')
  await expect(plan).toBeVisible()
  await shot(page, '04-split-radar-and-two-tracks', plan)
  await expect(plan.locator('[data-track="advanced"]')).toContainText('Level')
  await expect(plan.locator('[data-track="foundation"]')).toContainText('Level')

  // The plan as play: foundation first, with why on the pick.
  await plan.getByRole('button', { name: 'Play this plan' }).click()
  const pick = page.getByTestId('suggestion')
  await expect(pick).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('track-tag')).toContainText('Foundation track')
  await expect(page.getByTestId('why-box')).toBeVisible()
  await shot(page, '05-why-on-every-pick-foundation-track', pick)
  await page.getByRole('button', { name: 'See every option' }).click()
  await expect(page.getByTestId('why-card')).toBeVisible()
  await shot(page, '06-why-every-option-weighed')
  await page.getByTestId('why-card').getByRole('button', { name: 'Close' }).click()

  // Why audit in words, about today and about the past.
  await say(page, 'Why did you assign me this specific exercise today?')
  await expect(page.getByTestId('why-card-inline')).toBeVisible({ timeout: 60_000 })
  await shot(page, '07-why-audit-asked-in-chat', page.getByTestId('why-card-inline'))
  await say(page, 'What did I play this week?')
  await expect(page.getByTestId('history-card')).toBeVisible({ timeout: 60_000 })
  await shot(page, '08-history-asked-in-chat', page.getByTestId('history-card'))

  // Fortune teller: a range, never a number.
  await say(page, 'What exactly will my cognitive score be next month?')
  const forecast = page.getByTestId('forecast-card')
  await expect(forecast).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('chat')).toContainText("can't give you an exact number")
  await shot(page, '09-fortune-teller-gets-a-range', forecast)

  // Play the foundation round, and the next pick is the advanced track.
  await playCurrentGame(page)
  await expect(page.getByTestId('coach')).not.toContainText('Looking at your round', {
    timeout: 60_000,
  })
  const tag = page.getByTestId('track-tag').last()
  await expect(tag).toContainText('Advanced track', { timeout: 60_000 })
  await shot(page, '10-next-pick-advanced-track', page.getByTestId('suggestion').last())

  // Pushback: the range widens, the score rises, once.
  await say(page, "That's not fair, the room was so noisy I couldn't focus")
  const pushback = page.getByTestId('pushback-card')
  await expect(pushback).toBeVisible({ timeout: 60_000 })
  await shot(page, '11-pushback-accepted', pushback)
  await page.getByRole('button', { name: 'AI Collaboration' }).click()
  await expect(page.getByTestId('acs-pushback')).toBeVisible({ timeout: 30_000 })
  await shot(page, '12-pushback-on-collaboration-score')
  await page.getByRole('button', { name: 'Conversation' }).click()

  // Button masher: mash through a game, and the red screen comes up when it ends.
  await say(page, 'play Arrow Storm')
  await expect(page.getByTestId('suggestion').last()).toContainText('Arrow Storm', {
    timeout: 60_000,
  })
  await page
    .getByRole('button', { name: /Let's go|Next game/ })
    .last()
    .click()
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  const red = page.getByTestId('rushed')
  const done = page.getByRole('button', { name: 'Done', exact: true })
  for (let i = 0; i < 4000; i += 1) {
    if (await red.isVisible()) break
    // The odd "How sure?" question between answers gets mashed through too.
    if (await done.isVisible()) await done.click()
    await page.keyboard.press(i % 2 ? 'ArrowLeft' : 'ArrowRight')
    await page.waitForTimeout(25)
  }
  await expect(red).toBeVisible({ timeout: 30_000 })
  await expect(red).toContainText("That round didn't count")
  await shot(page, '13-button-masher-red-screen')
  await red.getByRole('button', { name: 'I got distracted' }).click()
  await shot(page, '14-button-masher-answered')
  await page.getByTestId('rushed-close').click()
  await expect(page.getByTestId('not-counted')).toBeVisible()
  await expect(page.getByTestId('chat')).toContainText('Were you distracted, or rushing?')
  await shot(page, '15-round-marked-not-counted-coach-asks', page.getByTestId('not-counted'))
})
