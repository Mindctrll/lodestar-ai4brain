import { execFileSync } from 'node:child_process'
import path from 'node:path'

import { expect, test } from '@playwright/test'

// WP3.2: ask the Twin a question on seeded data (UW8), then start an experiment (UW10).
function seededToken(): string {
  const out = execFileSync('uv', ['run', 'python', '-m', 'backend.db.seed', '--reset', '--token'], {
    cwd: path.resolve(import.meta.dirname, '..', '..'),
    encoding: 'utf8',
  })
  const line = out.split('\n').find((l) => l.startsWith('TOKEN='))
  if (!line) throw new Error(`seed printed no token: ${out}`)
  return line.slice('TOKEN='.length)
}

test('ask the Twin when I am sharpest, then start an experiment', async ({ page }) => {
  await page.goto(`/?signin=${seededToken()}`)
  await page.getByRole('button', { name: 'Brain Twin' }).click()
  const twin = page.getByRole('region', { name: 'Ask your Twin' })
  await twin.getByRole('textbox').fill('when am I sharpest?')
  await twin.getByRole('button', { name: 'Send' }).click()
  // First person, from facts (the chips), and honest about how sure it is.
  await expect(twin).toContainText(/My games go best in the (morning|evening)/, { timeout: 60_000 })
  await expect(twin.locator('.cite').first()).toBeVisible()

  await page.getByRole('button', { name: 'Experiments' }).click()
  await page.getByRole('button', { name: 'Start one' }).click()
  const confirm = page.getByTestId('confirm')
  await expect(confirm).toContainText('morning or the evening', { timeout: 60_000 })
  await confirm.getByRole('button', { name: 'Yes' }).click()
  await expect(page.getByTestId('chat')).toContainText('Experiment started', { timeout: 30_000 })

  await page.getByRole('button', { name: 'Experiments' }).click()
  const list = page.getByTestId('experiments')
  await expect(list).toContainText('Running')
  await expect(list).toContainText('0 of 3')
  await list.getByRole('button', { name: 'Stop this experiment' }).click()
  await expect(page.getByRole('button', { name: 'Start one' })).toBeVisible()
})
