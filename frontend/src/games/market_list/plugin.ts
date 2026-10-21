import { parse } from 'yaml'

import { shuffle } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { wait, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { voiceAnswer } from '../../voice/answer'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { fallback_words: string[] }

export interface ListItem {
  words: string[]
  speed_ms: number
}

export function recalled(typed: string, words: string[]): Set<string> {
  const said = new Set(
    typed
      .toLowerCase()
      .split(/[^a-z]+/)
      .filter(Boolean),
  )
  return new Set(words.filter((w) => said.has(w.toLowerCase())))
}

const ListPlugin = makePlugin<ListItem>(
  'najma-market-list',
  async ({ jsPsych, stage, item, e2e }) => {
    const word = el('div', 'ml-word')
    stage.append(word)
    for (const w of item.words) {
      word.textContent = w
      await wait(item.speed_ms * 0.8)
      word.textContent = ''
      await wait(item.speed_ms * 0.2)
    }
    word.remove()
    const input = el('textarea', 'ml-input')
    input.dataset['testid'] = 'recall-input'
    input.setAttribute('aria-label', 'Type the words you remember')
    input.placeholder = 'Type the words you remember, in any order'
    const done = button('Done', 'recall-done')
    // Saying the words is the same as typing them (registry modalities: voice).
    const say = voiceAnswer(input, 'Say them', (a) => a.transcript, 60_000)
    stage.append(input, say.button, done)
    input.focus()
    const started = performance.now()
    await waitForResponse(jsPsych, {
      keys: [],
      targets: [{ element: done, key: 'done' }],
      deadlineMs: 60_000,
      onReady: () => {
        markAnswer(stage, e2e, `type:${item.words.join(' ')}`)
      },
    })
    say.cancel()
    const got = recalled(input.value, item.words)
    const rt = performance.now() - started
    return item.words.map((w, i) => ({
      stimulus: { word: w, position: i, list_length: item.words.length },
      response: { typed: got.has(w) },
      correct: got.has(w),
      rt_ms: rt,
    }))
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  return {
    items_recalled: scored.filter((t) => t.correct === true).length,
    recall_share: scored.length
      ? scored.filter((t) => t.correct === true).length / scored.length
      : 0,
  }
}

export const game: GameModule = {
  id: 'market_list',
  name: 'Market List',
  instructions: 'Words will flash one at a time. Afterwards, type or say every word you remember.',
  keysHint: 'Type the words (or tap Say them and speak), then press Done.',
  timeline({ spec, rng, e2e }) {
    const lists = (spec.content?.['lists'] as string[][] | undefined) ?? [
      shuffle(rng, config.fallback_words).slice(0, Math.round(spec.knobs['list_length'] ?? 8)),
    ]
    const items = lists.map((words) => ({ words, speed_ms: spec.knobs['speed_ms'] ?? 1200 }))
    return itemsToTimeline(ListPlugin, items, 0, e2e)
  },
  metrics,
}
