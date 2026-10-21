import { parse } from 'yaml'

import { shuffle, type Rng } from '../../lib/rng'
import {
  button,
  el,
  itemsToTimeline,
  makePlugin,
  markAnswer,
  type TrialOutcome,
} from '../../taskhost/plugin'
import { wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { scored, taps } from '../shared/ask'
import rawConfig from './config.yaml?raw'

interface Deck {
  win: number
  /** Losses within each block of 10 cards. */
  losses: number[]
}

const config = parse(rawConfig) as {
  picks: number
  start_points: number
  deadline_ms: number
  decks: Deck[]
}

export interface Card {
  win: number
  loss: number
}

export interface GambleItem {
  /** Each deck's cards in order, enough for every pick. */
  decks: Card[][]
}

/** Iowa Gambling Task idea (Bechara et al., 1994): decks A and B pay more per card but lose
 * more over time; C and D pay less but come out ahead. Losses are shuffled within each block
 * of 10 cards. */
export function makeItem(rng: Rng): GambleItem {
  return {
    decks: config.decks.map((deck) =>
      Array.from({ length: Math.ceil(config.picks / 10) }, () =>
        shuffle(rng, [...deck.losses, ...Array<number>(10 - deck.losses.length).fill(0)]),
      )
        .flat()
        .map((loss) => ({ win: deck.win, loss })),
    ),
  }
}

/** Net over 10 cards of a deck: positive for the decks that pay off. */
export const deckNet = (deck: Deck) => deck.win * 10 - deck.losses.reduce((a, b) => a + b, 0)

const GOOD = config.decks.map((d) => deckNet(d) > 0)

const GamblePlugin = makePlugin<GambleItem>('najma-card-gamble', async ({ stage, item, e2e }) => {
  let points = config.start_points
  const total = el('p', 'game-prompt', `${String(points)} points`)
  const last = el('p', 'cg-last', 'Pick a card from any deck.')
  last.setAttribute('aria-live', 'polite')
  const row = el('div', 'choice-row')
  const decks = item.decks.map((_, i) => {
    const b = button('ABCD'[i] ?? '', `deck-${String(i)}`, 'cg-deck')
    b.setAttribute('aria-label', `Deck ${'ABCD'[i] ?? ''}`)
    return b
  })
  row.append(...decks)
  stage.append(total, row, last)
  const drawn = item.decks.map(() => 0)
  const outcomes: TrialOutcome[] = []
  let previous = 0
  await taps(
    decks.map((element, i) => ({ element, key: String(i + 1) })),
    {
      keys: ['1', '2', '3', '4'],
      deadlineMs: config.deadline_ms,
      onReady: () => {
        // End-to-end tests stick to the decks that pay off.
        const good = GOOD.flatMap((g, i) => (g ? [`deck-${String(i)}`] : []))
        const clicks = Array.from({ length: config.picks }, (_, i) => good[i % good.length])
        markAnswer(stage, e2e, `clicks:${clicks.join('|')}`)
      },
      onTap: (key, ms) => {
        const deck = Number(key) - 1
        const card = item.decks[deck]?.[drawn[deck] ?? 0] ?? { win: 0, loss: 0 }
        drawn[deck] = (drawn[deck] ?? 0) + 1
        points += card.win - card.loss
        total.textContent = `${String(points)} points`
        last.textContent =
          card.loss > 0
            ? `You won ${String(card.win)} but lost ${String(card.loss)}.`
            : `You won ${String(card.win)}.`
        outcomes.push({
          stimulus: { pick: outcomes.length, deck, win: card.win, loss: card.loss },
          response: { deck, good: GOOD[deck] === true, points },
          correct: null, // a style, not right or wrong
          rt_ms: ms - previous,
        })
        previous = ms
        return outcomes.length >= config.picks
      },
    },
  )
  await wait(700)
  return outcomes
})

/** Advantageous choices: picks from the decks that pay off minus the others, overall and in
 * the second half (once the decks could be learned). */
export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const net = (list: TrialRecord[]) =>
    list.reduce((n, t) => n + (t.response?.['good'] === true ? 1 : -1), 0)
  return {
    advantageous_choices: net(s),
    late_advantageous: net(s.slice(Math.floor(s.length / 2))),
    points: Number(s[s.length - 1]?.response?.['points'] ?? config.start_points),
  }
}

export const game: GameModule = {
  id: 'card_gamble',
  name: 'Card Gamble',
  instructions:
    'Pick cards from four decks. Each card wins points, and some also lose points. Some decks do better over time than others. There’s no right way: this shows your style.',
  keysHint: 'Tap a deck, or press 1 to 4.',
  timeline({ rng, e2e }) {
    return itemsToTimeline(GamblePlugin, [makeItem(rng)], 0, e2e)
  },
  metrics,
}
