import { expect, test } from '@playwright/test'

import { expectWellFormed, playCurrentGame, prepare, startSession } from './helpers'

// Playwright plays each reference game with scripted input; the API must receive correct trial
// events (WP1.3 "Done when").
const GAMES = [
  { id: 'quick_draw', ask: 'play Quick Draw' },
  { id: 'ink_clash', ask: 'play Ink Clash' },
  { id: 'echo', ask: 'play Echo' },
]

for (const { id, ask } of GAMES) {
  test(`plays ${id} and sends correct trial events`, async ({ page }) => {
    const sent = await prepare(page)
    await startSession(page, ask)
    await playCurrentGame(page)
    await expect(page.getByTestId('coach')).not.toBeEmpty({ timeout: 60_000 })
    const trials = sent.filter((t) => t.game_id === id)
    expectWellFormed(trials, id)
    const scored = trials.filter((t) => !t.practice)
    const right = scored.filter((t) => t.correct === true).length
    // We always give the expected answer; allow one miss for timing at the deadline.
    expect(right).toBeGreaterThanOrEqual(scored.length - 1)
    if (id !== 'echo') {
      for (const t of scored.filter((x) => x.correct === true)) expect(t.rt_ms).toBeGreaterThan(0)
    }
  })
}
