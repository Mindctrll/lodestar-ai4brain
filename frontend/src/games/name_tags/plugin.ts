import { parse } from 'yaml'

import { shuffle, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin, type TrialOutcome } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { accuracy, choose, nextAnswer } from '../shared/ask'
import { node, svg } from '../shared/svg'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as {
  sets: number
  study_ms_per_pair: number
  deadline_ms: number
  options: number
  names: string[]
  hair_colours: string[]
  shirts: string[]
}

/** A drawn character (never a real face): hair style and colour, shirt, and one extra. */
export interface Look {
  hair: number
  hair_colour: string
  shirt: string
  extra: number
}

export interface TagsItem {
  people: { name: string; look: Look }[]
  /** Each question: the person shown and the people whose names are offered. */
  questions: { person: number; options: number[] }[]
}

const LOOKS: Look[] = [0, 1, 2].flatMap((hair) =>
  config.hair_colours.flatMap((hairColour) =>
    config.shirts.flatMap((shirt) =>
      [0, 1, 2, 3].map((extra) => ({ hair, hair_colour: hairColour, shirt, extra })),
    ),
  ),
)

export function makeItems(rng: Rng, count: number, pairs: number): TagsItem[] {
  return Array.from({ length: count }, () => {
    const names = shuffle(rng, config.names).slice(0, pairs)
    const looks = shuffle(rng, LOOKS)
    const people = names.map((name, i) => ({ name, look: looks[i] as Look }))
    const questions = shuffle(
      rng,
      people.map((_, i) => i),
    ).map((person) => ({
      person,
      options: shuffle(rng, [
        person,
        ...shuffle(
          rng,
          people.map((_, j) => j).filter((j) => j !== person),
        ).slice(0, config.options - 1),
      ]),
    }))
    return { people, questions }
  })
}

export function drawPerson(look: Look): SVGSVGElement {
  const s = svg(60, 80, 'A drawn character')
  const hair = { fill: look.hair_colour }
  if (look.hair === 1)
    s.append(node('rect', { x: 14, y: 22, width: 32, height: 30, rx: 8, ...hair }))
  s.append(node('path', { d: 'M8 80 Q8 54 30 54 Q52 54 52 80 Z', fill: look.shirt }))
  s.append(node('circle', { cx: 30, cy: 34, r: 14, fill: '#f2c9a0' }))
  s.append(
    node('path', { d: 'M16 32 Q16 18 30 18 Q44 18 44 32 Q37 25 30 25 Q23 25 16 32 Z', ...hair }),
  )
  if (look.hair === 2) s.append(node('circle', { cx: 30, cy: 15, r: 6, ...hair }))
  for (const x of [25, 35]) s.append(node('circle', { cx: x, cy: 35, r: 1.6, fill: '#222' }))
  s.append(
    node('path', { d: 'M25 41 Q30 45 35 41', fill: 'none', stroke: '#222', 'stroke-width': 1.2 }),
  )
  const line = { fill: 'none', stroke: '#222', 'stroke-width': 1.4 }
  if (look.extra === 1) {
    for (const x of [25, 35]) s.append(node('circle', { cx: x, cy: 35, r: 4, ...line }))
    s.append(node('line', { x1: 29, y1: 35, x2: 31, y2: 35, ...line }))
  }
  if (look.extra === 2) {
    s.append(node('rect', { x: 12, y: 18, width: 36, height: 4, fill: '#333' }))
    s.append(node('rect', { x: 19, y: 6, width: 22, height: 13, fill: '#333' }))
  }
  if (look.extra === 3)
    s.append(node('rect', { x: 20, y: 50, width: 20, height: 6, rx: 3, fill: '#e0a400' }))
  return s
}

function card(look: Look, name?: string): HTMLElement {
  const box = el('figure', 'nt-card')
  box.append(drawPerson(look))
  if (name !== undefined) box.append(el('figcaption', '', name))
  return box
}

const TagsPlugin = makePlugin<TagsItem>(
  'najma-name-tags',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const grid = el('div', 'nt-grid')
    grid.append(...item.people.map((p) => card(p.look, p.name)))
    stage.append(el('p', 'game-prompt', 'Remember each name.'), grid)
    await wait(item.people.length * config.study_ms_per_pair)
    const outcomes: TrialOutcome[] = []
    for (const [k, q] of item.questions.entries()) {
      const person = item.people[q.person]
      if (!person) continue
      nextAnswer(stage, k)
      stage.replaceChildren(el('p', 'game-prompt', 'What is this one called?'), card(person.look))
      const { index, rt } = await choose(
        jsPsych,
        stage,
        e2e,
        q.options.map((o) => item.people[o]?.name ?? ''),
        q.options.indexOf(q.person),
        { deadlineMs: config.deadline_ms },
      )
      const correct = index !== null && q.options[index] === q.person
      if (practice) await practiceFeedback(stage, correct)
      outcomes.push({
        stimulus: { name: person.name, pairs: item.people.length },
        response: index === null ? null : { picked: item.people[q.options[index] ?? -1]?.name },
        correct,
        rt_ms: rt,
      })
    }
    return outcomes
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  return { accuracy: accuracy(trials) }
}

export const game: GameModule = {
  id: 'name_tags',
  name: 'Name Tags',
  instructions:
    'Meet a few characters and remember their names. Then each one comes back: pick the right name.',
  keysHint: 'Tap the name.',
  timeline({ spec, rng, e2e }) {
    const practice = Math.min(1, spec.practice_trials)
    const pairs = Math.round(spec.knobs['pairs'] ?? 4)
    const items = [...makeItems(rng, practice, 2), ...makeItems(rng, config.sets, pairs)]
    return itemsToTimeline(TagsPlugin, items, practice, e2e)
  },
  metrics,
}
