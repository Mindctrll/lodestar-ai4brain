import { execFileSync } from 'node:child_process'
import path from 'node:path'

import { expect, test, type Page } from '@playwright/test'

// The pages that show the whole system (docs/plan/13, "Pages that show the whole system"), on the
// seeded demo user: Games, Coach, Insights, Memory and Under the hood.

const ROOT = path.resolve(import.meta.dirname, '..', '..')
let token = ''

test.describe.configure({ mode: 'serial' })

test.beforeAll(() => {
  const out = execFileSync('uv', ['run', 'python', '-m', 'backend.db.seed', '--reset', '--token'], {
    cwd: ROOT,
    encoding: 'utf8',
  })
  const line = out.split('\n').find((l) => l.startsWith('TOKEN='))
  if (!line) throw new Error(`seed printed no token: ${out}`)
  token = line.slice('TOKEN='.length)
  // The demo user's memories live where the app keeps them: inside the backend container.
  execFileSync(
    'docker',
    ['compose', 'exec', '-T', 'backend', 'python', '-m', 'backend.db.seed_memory'],
    {
      cwd: ROOT,
      encoding: 'utf8',
    },
  )
})

async function open(page: Page, name: string) {
  if (!page.url().includes('localhost')) await page.goto(`/?signin=${token}`)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name }).click()
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
}

test('games: the story, a game made to order, filters, and Play opens the game', async ({
  page,
}) => {
  await open(page, 'Games')
  const games = page.getByTestId('games')
  await expect(games.locator('.story-card')).toContainText('Detective')
  await expect(games.locator('.story-card__chapters li')).toHaveCount(3)
  await expect(games.getByRole('button', { name: 'Make me a game' })).toBeVisible()
  expect(await games.locator('.game-card').count()).toBeGreaterThan(30)

  await games
    .getByRole('group', { name: 'Skill family' })
    .getByRole('button', { name: 'Memory' })
    .click()
  const memoryGames = games.locator('.game-card')
  await expect(memoryGames.filter({ hasText: 'Echo' })).toHaveCount(1)
  expect(await memoryGames.count()).toBeLessThan(15)

  await games
    .getByRole('group', { name: 'Skill family' })
    .getByRole('button', { name: 'All' })
    .click()
  await games
    .locator('.game-card', { hasText: 'Ink Clash' })
    .getByRole('button', { name: 'Play' })
    .click()
  // Play goes to the conversation, as if the user had asked for the game.
  await expect(page.getByTestId('suggestion').last().locator('h2')).toHaveText('Ink Clash', {
    timeout: 60_000,
  })
})

test('coach: four voices, and a switch that sticks', async ({ page }) => {
  await open(page, 'Coach')
  const cards = page.locator('.coach-card')
  await expect(cards).toHaveCount(4)
  await expect(page.locator('.coach-card--mine h2')).toHaveText('Willow')
  await page.getByRole('button', { name: 'Choose Sage' }).click()
  await expect(page.locator('.coach-card--mine h2')).toHaveText('Sage')

  const me = await page.request.get('/api/me', { headers: { Authorization: `Bearer ${token}` } })
  expect(((await me.json()) as { persona: string }).persona).toBe('sage')
  await page.reload()
  await open(page, 'Coach')
  await expect(page.locator('.coach-card--mine h2')).toHaveText('Sage')
  await page.getByRole('button', { name: 'Choose Willow' }).click()
  await expect(page.locator('.coach-card--mine h2')).toHaveText('Willow')
})

test('insights: every reading comes with its range', async ({ page }) => {
  await open(page, 'Insights')
  const insights = page.getByTestId('insights')
  const ahead = insights.locator('.heading-to li')
  await expect(ahead.first()).toBeVisible()
  expect(await ahead.count()).toBeGreaterThan(2)
  for (const row of await ahead.all()) await expect(row).toContainText(/likely \d+%-\d+%/)
  await expect(insights).toContainText(/You do best in the [a-z ]+\./)
  await expect(insights).toContainText(/start slowing after about \d+ minutes/)
  await expect(insights.locator('.tire__axis')).toContainText(/likely \d+-\d+ min/)
  await expect(insights).toContainText(/You were right\s*\d+%-\d+%/)
  await expect(insights).toContainText(/You played on \d of the last 7 days/)
  // The engagement-risk score is never shown as a number about the person.
  await expect(insights).not.toContainText(/risk/i)
})

test('memory: notes, moments and facts, and forgetting a line', async ({ page }) => {
  await open(page, 'Memory')
  const memory = page.getByTestId('memory')
  await expect(memory).toContainText('Plays best in the evening, after work.')
  expect(await memory.locator('.timeline li').count()).toBeGreaterThan(3)
  await expect(memory).toContainText('Best time of day: evening')
  await expect(memory).toContainText('exam week')

  const line = memory.locator('.notes li', { hasText: 'Prefers short sessions on busy days.' })
  await line.hover()
  await line.getByRole('button', { name: 'Forget' }).click()
  await expect(memory).not.toContainText('Prefers short sessions on busy days.')
})

test('under the hood: the models with their evaluation, the simulator and the rules', async ({
  page,
}) => {
  await open(page, 'Under the hood')
  const about = page.getByTestId('about')
  await expect(about.locator('.arch__layer')).toHaveCount(4)
  const forecast = about.locator('.model', { hasText: 'Growth forecast' })
  await expect(forecast).toContainText(/Ranges that held\s*\d+%/)
  const risk = about.locator('.model', { hasText: 'Engagement risk' })
  await expect(risk).toContainText(/AUC\s*0\.\d\d/)
  await expect(about.locator('.sim tbody tr')).toHaveCount(5)
  await expect(about.locator('.rules li')).toHaveCount(6)
})
