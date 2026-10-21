import { expect, test } from '@playwright/test'

import { playCurrentGame, prepare, startSession } from './helpers'

// Wave 1 gate (docs/plan/16): open the app, start a session, play Quick Draw, see the Twin change,
// and receive the coach's reply over the WebSocket.
test('wave 1 gate: play Quick Draw, the Twin updates, the coach replies', async ({ page }) => {
  await prepare(page)
  const frames: string[] = []
  page.on('websocket', (ws) => {
    ws.on('framereceived', (frame) => {
      if (typeof frame.payload === 'string') frames.push(frame.payload)
    })
  })
  await startSession(page, 'play Quick Draw')
  const token = await page.evaluate(() => localStorage.getItem('najma.token'))
  const before = await page.request.get('/api/twin', {
    headers: { Authorization: `Bearer ${token ?? ''}` },
  })
  expect(((await before.json()) as { dims: unknown[] }).dims).toEqual([])

  await playCurrentGame(page)
  await expect(page.getByTestId('coach')).toContainText('[F', { timeout: 60_000 })
  expect(frames.some((f) => f.includes('"kind": "say"') || f.includes('"kind":"say"'))).toBe(true)

  const after = await page.request.get('/api/twin', {
    headers: { Authorization: `Bearer ${token ?? ''}` },
  })
  const { dims } = (await after.json()) as { dims: { dim: string; n: number }[] }
  expect(dims.find((d) => d.dim === 'processing_speed')?.n).toBeGreaterThan(0)
})
