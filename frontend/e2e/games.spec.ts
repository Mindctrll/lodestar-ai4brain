import { expect, test } from '@playwright/test'

import { expectWellFormed, playCurrentGame, prepare, startSession } from './helpers'

// Playwright plays each core game with scripted, human-paced input; the API must receive
// well-formed trial events whose correctness matches the answers given (WP1.3, WP2.1).
const GAMES = [
  { id: 'quick_draw', name: 'Quick Draw' },
  { id: 'ink_clash', name: 'Ink Clash' },
  { id: 'echo', name: 'Echo' },
  { id: 'arrow_storm', name: 'Arrow Storm' },
  { id: 'odd_one_out', name: 'Odd One Out' },
  { id: 'hold_it', name: 'Hold It' },
  { id: 'light_path', name: 'Light Path' },
  { id: 'market_list', name: 'Market List' },
  { id: 'souk_rush', name: 'Souk Rush' },
  { id: 'symbol_code', name: 'Symbol Code' },
  { id: 'switch', name: 'Switch' },
  { id: 'pattern_gap', name: 'Pattern Gap' },
  { id: 'spot_the_mistake', name: "Spot the AI's Mistake" },
  { id: 'turn_it', name: 'Turn It' },
  { id: 'number_line', name: 'Number Line' },
]

const only = process.env['NAJMA_GAMES']?.split(',')

for (const { id, name } of GAMES.filter((g) => !only || only.includes(g.id))) {
  test(`plays ${id} and sends correct trial events`, async ({ page }) => {
    const sent = await prepare(page)
    await startSession(page, `play ${name}`)
    await expect(page.getByTestId('suggestion')).toContainText(name)
    await playCurrentGame(page)
    await expect(page.getByTestId('coach')).not.toBeEmpty({ timeout: 60_000 })
    const trials = sent.filter((t) => t.game_id === id)
    expectWellFormed(trials, id)
    const scored = trials.filter((t) => !t.practice)
    const right = scored.filter((t) => t.correct === true).length
    // We always give the expected answer; allow one miss for timing at a deadline.
    expect(right).toBeGreaterThanOrEqual(scored.length - 1)
  })
}
