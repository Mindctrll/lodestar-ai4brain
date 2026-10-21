import { parse } from 'yaml'

import { shuffle, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { voiceAnswer } from '../../voice/answer'
import { scored, taps } from '../shared/ask'
import rawConfig from './config.yaml?raw'

interface Idea {
  idea: string
  words: string[]
}
interface Topic {
  id: string
  name: string
  question: string
  difficulty: number
  ideas: Idea[]
}

const config = parse(rawConfig) as {
  topics_per_round: number
  seconds: number
  enough_words: number
  pass: number
  topics: Topic[]
}

export interface TeachItem {
  topic: Topic
  /** On ambiguous items Najma names two things and says "it"; asking which one is the move. */
  other: Topic | null
  seconds: number
}

/** Topics nearest the difficulty knob; one item per round is ambiguous (docs/plan/11, C). */
export function makeItems(rng: Rng, count: number, difficulty: number): TeachItem[] {
  const near = [...config.topics].sort(
    (a, b) => Math.abs(a.difficulty - difficulty) - Math.abs(b.difficulty - difficulty),
  )
  const picked = shuffle(rng, near.slice(0, count + 2)).slice(0, count)
  const ambiguous = shuffle(
    rng,
    picked.map((_, i) => i === 0),
  )
  return picked.map((topic, i) => ({
    topic,
    other: ambiguous[i] ? (near.find((t) => !picked.includes(t)) ?? null) : null,
    seconds: config.seconds,
  }))
}

/** The rubric, scored in code: the share of the topic's key ideas the explanation mentions,
 * scaled down for very short answers. The plan's AI rating can replace this later; until then
 * it counts at the game's low weight (registry reliability 0.5). */
export function rubric(text: string, topic: Topic): { score: number; covered: string[] } {
  const words = text
    .toLowerCase()
    .split(/[^a-z]+/)
    .filter(Boolean)
  const said = new Set(words)
  const covered = topic.ideas
    .filter((i) =>
      i.words.some((w) => (w.includes(' ') ? text.toLowerCase().includes(w) : said.has(w))),
    )
    .map((i) => i.idea)
  const length = Math.min(1, words.length / config.enough_words)
  return { score: (covered.length / topic.ideas.length) * length, covered }
}

const TeachPlugin = makePlugin<TeachItem>('najma-teach-me', async ({ stage, item, e2e }) => {
  const ask =
    item.other === null
      ? `Najma: ${item.topic.question} Can you explain it to me?`
      : `Najma: I read about ${item.topic.name} and about ${item.other.name}. I don’t get how it works. Can you explain?`
  const reply = el('p', 'gr-reply')
  reply.setAttribute('aria-live', 'polite')
  const input = el('textarea', 'ml-input')
  input.dataset['testid'] = 'recall-input'
  input.setAttribute('aria-label', 'Your explanation')
  input.placeholder = 'Explain it in your own words'
  const which = button('Ask what Najma means', 'teach-ask')
  const say = voiceAnswer(input, 'Say it', (a) => a.transcript, 60_000)
  const done = button('Done', 'recall-done')
  const row = el('div', 'type-row')
  row.append(which, say.button, done)
  stage.append(el('p', 'game-prompt', ask), reply, input, row)
  let asked = false
  let askedFirst = false
  const started = performance.now()
  let typedBeforeAsk = false
  input.addEventListener('input', () => {
    if (!asked) typedBeforeAsk = input.value.trim().length > 20
  })
  await taps(
    [
      { element: which, key: 'ask' },
      { element: done, key: 'done' },
    ],
    {
      deadlineMs: item.seconds * 1000,
      onReady: () => {
        const answer = item.topic.ideas.map((i) => i.idea).join(' ')
        markAnswer(stage, e2e, `${item.other ? 'click:teach-ask >> ' : ''}type:${answer}`)
        input.focus()
      },
      onTap: (key) => {
        if (key === 'done') return true
        if (!asked) askedFirst = !typedBeforeAsk
        asked = true
        reply.textContent =
          item.other === null
            ? `Najma: ${item.topic.name}, like I said.`
            : `Najma: Sorry, I meant ${item.topic.name}.`
        return false
      },
    },
  )
  say.cancel()
  const { score, covered } = rubric(input.value, item.topic)
  reply.textContent =
    score >= config.pass
      ? 'Najma: Oh, I get it now. Thanks!'
      : 'Najma: Hmm, I’m still a bit lost, but thanks.'
  await wait(800)
  return {
    stimulus: {
      topic: item.topic.id,
      ambiguous: item.other !== null,
      ideas: item.topic.ideas.length,
    },
    response: {
      score,
      covered,
      asked,
      asked_first: askedFirst,
      words: input.value.split(/\s+/).length,
    },
    correct: score >= config.pass,
    rt_ms: performance.now() - started,
  }
})

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const scores = s.map((t) => Number(t.response?.['score'] ?? 0))
  return {
    rubric_score: scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0,
    clarifications: s.filter((t) => t.response?.['asked'] === true).length,
  }
}

export const game: GameModule = {
  id: 'teach_me',
  name: 'Teach Me',
  instructions:
    'Najma is confused about something. Explain it simply, in your own words. If you’re not sure what Najma is asking about, ask first.',
  keysHint: 'Type your explanation, then Done.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(rng, config.topics_per_round, spec.knobs['topic_difficulty'] ?? 0.4)
    return itemsToTimeline(TeachPlugin, items, 0, e2e)
  },
  metrics,
}
