import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { recalled } from '../market_list/plugin'
import { scored, typeIn } from '../shared/ask'

export interface CallbackItem {
  words: string[]
}

const CallbackPlugin = makePlugin<CallbackItem>(
  'lodestar-callback',
  async ({ jsPsych, stage, item, e2e }) => {
    stage.append(el('p', 'game-prompt', 'Earlier in this session you learned a market list.'))
    const { text, rt } = await typeIn(jsPsych, stage, e2e, item.words.join(' '), {
      label: 'Type every word you still remember',
      deadlineMs: 60_000,
      multiline: true,
    })
    const got = recalled(text, item.words)
    return item.words.map((w, i) => ({
      stimulus: { word: w, position: i, list_length: item.words.length },
      response: { typed: got.has(w) },
      correct: got.has(w),
      rt_ms: rt,
    }))
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  return {
    delayed_recall_share: s.length ? s.filter((t) => t.correct === true).length / s.length : 0,
  }
}

export const game: GameModule = {
  id: 'callback',
  name: 'Callback',
  instructions: 'Remember the market list from earlier? Type every word you still remember.',
  keysHint: 'Type the words, any order, then Done.',
  timeline({ spec, e2e }) {
    // The server sends the words of this session's Market List round.
    const words = (spec.content?.['words'] as string[] | undefined) ?? []
    if (words.length === 0)
      throw new Error('Callback needs a Market List round earlier in the session.')
    return itemsToTimeline(CallbackPlugin, [{ words }], 0, e2e)
  },
  metrics,
}
