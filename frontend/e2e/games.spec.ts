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
  // P2 (WP3.1). Callback needs a Market List first: see callback.spec.ts.
  { id: 'brake', name: 'Brake' },
  { id: 'look_here', name: 'Look Here' },
  { id: 'night_guard', name: 'Night Guard' },
  { id: 'control_tower', name: 'Control Tower' },
  { id: 'digits_back', name: 'Digits Back' },
  { id: 'seen_it', name: 'Seen It?' },
  { id: 'twins', name: 'Twins' },
  { id: 'connect', name: 'Connect' },
  { id: 'zigzag', name: 'Zigzag' },
  { id: 'secret_rules', name: 'Secret Rules' },
  { id: 'tower', name: 'Tower' },
  { id: 'guide_the_robot', name: 'Guide the Robot' },
  { id: 'logic_lock', name: 'Logic Lock' },
  { id: 'word_burst', name: 'Word Burst' },
  { id: 'scramble', name: 'Scramble' },
  { id: 'teach_me', name: 'Teach Me' },
  { id: 'which_jar', name: 'Which Jar?' },
  { id: 'quick_maths', name: 'Quick Maths' },
  { id: 'balloon_pump', name: 'Balloon Pump' },
  // Late games (WP3.10).
  { id: 'two_screens', name: 'Two Screens' },
  { id: 'sum_and_keep', name: 'Sum & Keep' },
  { id: 'name_tags', name: 'Name Tags' },
  { id: 'maze_escape', name: 'Maze Escape' },
  { id: 'fold_and_punch', name: 'Fold & Punch' },
  { id: 'card_gamble', name: 'Card Gamble' },
  { id: 'unusual_uses', name: 'Unusual Uses' },
  // New dimension from the WP4.4 drill
  { id: 'off_beat', name: 'Off Beat' },
]

// Games with only a few long steps: one minute of words, three explanations, two objects.
const FEW_STEPS: Record<string, number> = { word_burst: 1, teach_me: 3, unusual_uses: 2 }

const only = process.env['NAJMA_GAMES']?.split(',')

for (const { id, name } of GAMES.filter((g) => !only || only.includes(g.id))) {
  test(`plays ${id} and sends correct trial events`, async ({ page }) => {
    const sent = await prepare(page)
    await startSession(page, `play ${name}`)
    await expect(page.getByTestId('suggestion')).toContainText(name)
    await playCurrentGame(page)
    await expect(page.getByTestId('coach')).not.toBeEmpty({ timeout: 60_000 })
    const trials = sent.filter((t) => t.game_id === id)
    expectWellFormed(trials, id, FEW_STEPS[id])
    // Steps that aren't right or wrong (Balloon Pump, Zigzag's baseline board) aren't counted.
    const scored = trials.filter((t) => !t.practice && t.correct !== null)
    const right = scored.filter((t) => t.correct === true).length
    // We always give the expected answer; allow one miss for timing at a deadline.
    expect(right).toBeGreaterThanOrEqual(scored.length - 1)
  })
}
