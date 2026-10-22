import { expect, test } from '@playwright/test'

import { prepare } from './helpers'

// UW1: the first-visit screens, with the camera never touched.
test('first visit: welcome, 18+, consent, coach, then practice', async ({ page }) => {
  await prepare(page, { firstVisit: true })
  await page.addInitScript(() => {
    const w = window as unknown as { __cameraCalls: number }
    w.__cameraCalls = 0
    const devices = navigator.mediaDevices as MediaDevices | undefined
    if (devices) {
      devices.getUserMedia = () => {
        w.__cameraCalls += 1
        return Promise.reject(new Error('not in this test'))
      }
    }
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Get started' }).click()
  await page.getByRole('button', { name: "I'm 18 or older" }).click()
  await page.getByRole('checkbox', { name: /Microphone/ }).check()
  await expect(page.getByRole('checkbox', { name: /Core practice data/ })).toBeDisabled()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('radio', { name: /Sage/ }).check()
  await page.getByRole('button', { name: "Let's start" }).click()
  await expect(page.getByRole('button', { name: 'Start a session' })).toBeVisible()

  const token = await page.evaluate(() => localStorage.getItem('lodestar.token'))
  const consent = await page.request.get('/api/consent', {
    headers: { Authorization: `Bearer ${token ?? ''}` },
  })
  const switches = ((await consent.json()) as { switches: { id: string; granted: boolean }[] })
    .switches
  const state = Object.fromEntries(switches.map((s) => [s.id, s.granted]))
  expect(state).toMatchObject({ core: true, microphone: true, camera: false, cloud_ai: false })
  expect(
    await page.evaluate(() => (window as unknown as { __cameraCalls: number }).__cameraCalls),
  ).toBe(0)
})

// UW14 and UW22: switches, the cloud consent step, export, and delete with a receipt.
test('settings: switches, cloud AI consent, export, delete with a receipt', async ({ page }) => {
  await prepare(page)
  await page.goto('/')
  const token = await page.evaluate(() => localStorage.getItem('lodestar.token'))
  await page.getByRole('button', { name: 'Settings' }).click()

  const planted = page.getByRole('checkbox', { name: /planted mistakes/ })
  await expect(planted).toBeChecked()
  await planted.uncheck()
  await expect(planted).not.toBeChecked()

  await page.getByRole('tab', { name: 'AI provider' }).click()
  await expect(page.getByTestId('local-badge')).toBeVisible()
  await page.getByRole('button', { name: 'Add key' }).first().click()
  const ask = page.getByTestId('cloud-consent')
  await expect(ask).toContainText('processes data in')
  await ask.getByRole('button', { name: 'Not now' }).click()

  await page.getByRole('tab', { name: 'Memory & data' }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export my data' }).click()
  expect((await download).suggestedFilename()).toBe('lodestar-export.json')

  await page.getByRole('button', { name: 'Delete everything' }).click()
  await page
    .getByTestId('delete-confirm')
    .getByRole('button', { name: 'Yes, delete everything' })
    .click()
  await expect(page.getByTestId('receipt')).toContainText('Deleted')
  const after = await page.request.get('/api/consent', {
    headers: { Authorization: `Bearer ${token ?? ''}` },
  })
  expect(after.status()).toBe(401)
})
