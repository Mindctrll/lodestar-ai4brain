import { execFileSync } from 'node:child_process'
import path from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { playCurrentGame, prepare, startSession } from './helpers'

// WP2.5 "Done when": visual tests on seeded data, every chart shows its range, and the dashboard
// updates live when the Twin changes (docs/plan/13).

function seededToken(): string {
  const out = execFileSync('uv', ['run', 'python', '-m', 'backend.db.seed', '--reset', '--token'], {
    cwd: path.resolve(import.meta.dirname, '..', '..'),
    encoding: 'utf8',
  })
  const line = out.split('\n').find((l) => l.startsWith('TOKEN='))
  if (!line) throw new Error(`seed printed no token: ${out}`)
  return line.slice('TOKEN='.length)
}

async function chartSeries(page: Page): Promise<string[]> {
  return page
    .getByTestId('chart')
    .evaluateAll((els) => els.map((e) => e.getAttribute('data-series') ?? ''))
}

test('seeded dashboard: every view renders, and every estimate shows its range', async ({
  page,
}, testInfo) => {
  const errors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
  })
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto(`/?signin=${seededToken()}`)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    /Good (morning|afternoon|evening)/,
  )
  await expect(page.getByLabel('Your week')).toContainText('rounds this week')
  await expect(page).not.toHaveURL(/signin=/) // the token leaves the address bar
  await testInfo.attach('home', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  })

  // Night sky: blur follows uncertainty; unmeasured skills say so.
  await page.getByRole('button', { name: 'Brain Twin' }).click()
  const sky = page.getByTestId('night-sky')
  await expect(sky).toBeVisible()
  const stars = await sky.locator('[data-dim]').evaluateAll((els) =>
    els.map((e) => ({
      dim: e.getAttribute('data-dim'),
      blur: e.getAttribute('data-blur'),
      label: e.getAttribute('aria-label') ?? '',
    })),
  )
  const measured = stars.filter((s) => s.blur !== 'none')
  expect(measured.length).toBeGreaterThan(5)
  for (const s of measured) expect(s.label).toMatch(/\d+%, likely \d+% to \d+%/)
  expect(
    stars.filter((s) => s.blur === 'none').every((s) => s.label.includes('not measured yet')),
  ).toBe(true)
  expect(await chartSeries(page)).toEqual(['80% range|Estimate'])
  await testInfo.attach('twin', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  })

  // A skill page from the sky.
  await sky.locator('[data-dim="working_memory"]').click()
  await expect(page.getByTestId('skill-page')).toContainText('Working memory')
  await expect(page.getByTestId('skill-page')).toContainText(/likely \d+-\d+%/)
  await page.getByRole('button', { name: /Back to the sky/ }).click()

  // Progress: curves with range bands (and forecast ranges), heatmaps, goals.
  await page.getByRole('button', { name: 'Progress' }).click()
  await expect(page.getByTestId('goals')).toContainText('Working memory')
  const series = await chartSeries(page)
  const curves = series.filter((s) => s.includes('Estimate'))
  expect(curves.length).toBeGreaterThan(5)
  for (const s of curves) expect(s).toContain('80% range')
  expect(curves.some((s) => s.includes('Forecast 80% range'))).toBe(true)
  for (const s of curves.filter((x) => x.includes('Forecast')))
    expect(s).toContain('Forecast 80% range') // a forecast never without its range
  expect(series.some((s) => s.startsWith('Change per week'))).toBe(true)
  expect(series.some((s) => s.startsWith('Share right'))).toBe(true)
  await testInfo.attach('progress', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  })

  // Collaboration score: a gauge with its range, and a range per part.
  await page.getByRole('button', { name: 'AI collaboration' }).click()
  expect(await chartSeries(page)).toEqual(['Score with 80% range'])
  await expect(page.getByTestId('acs')).toContainText(/\d+ \(\d+-\d+\), from \d+ moments/)

  // Agent: the graph and decisions.
  await page.getByRole('button', { name: 'Agent' }).click()
  await expect(page.getByLabel('Agent graph')).toContainText('plan next')
  expect(errors).toEqual([])
})

test('the Twin updates live while another tab plays', async ({ page, context }) => {
  await prepare(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Brain Twin' }).click()
  const speed = page.getByTestId('night-sky').locator('[data-dim="processing_speed"]')
  await expect(speed).toHaveAttribute('data-blur', 'none')

  const player = await context.newPage()
  await player.addInitScript(() => {
    ;(window as unknown as { __LODESTAR_E2E__: boolean }).__LODESTAR_E2E__ = true
  })
  await startSession(player, 'play Quick Draw')
  await playCurrentGame(player)
  // No reload in the first tab: the scored round's NOTIFY reaches it over /twin/stream.
  await expect(speed).not.toHaveAttribute('data-blur', 'none', { timeout: 30_000 })
  await expect(speed).toHaveAttribute('aria-label', /Processing speed: \d+%, likely/)
})
