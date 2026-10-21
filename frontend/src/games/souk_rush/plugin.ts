import { parse } from 'yaml'

import { shuffle, type Rng } from '../../lib/rng'
import { button, el, itemsToTimeline, makePlugin, markAnswer } from '../../taskhost/plugin'
import { wait, waitForResponse } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import rawConfig from './config.yaml?raw'

const config = parse(rawConfig) as { read_ms_per_item: number; extra_choices: number }

interface Order {
  customer: string
  items: string[]
  line: string
}
interface Change {
  customer: string
  remove: string
  add: string
  line: string
}
export interface Scene {
  orders: Order[]
  changes: Change[]
}

export function finalOrders(scene: Scene): Map<string, string[]> {
  const out = new Map(scene.orders.map((o) => [o.customer, [...o.items]]))
  for (const c of scene.changes) {
    const items = out.get(c.customer)
    if (items)
      out.set(
        c.customer,
        items.map((i) => (i === c.remove ? c.add : i)),
      )
  }
  return out
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z]+/g, '-')

interface SceneItem {
  scene: Scene
  choices: Record<string, string[]>
}

export function makeItems(scenes: Scene[], rng: Rng): SceneItem[] {
  return scenes.map((scene) => {
    const all = [
      ...new Set(scene.orders.flatMap((o) => o.items).concat(scene.changes.map((c) => c.add))),
    ]
    const finals = finalOrders(scene)
    const choices: Record<string, string[]> = {}
    for (const [customer, items] of finals) {
      const extras = shuffle(
        rng,
        all.filter((i) => !items.includes(i)),
      ).slice(0, config.extra_choices)
      choices[customer] = shuffle(rng, [...items, ...extras])
    }
    return { scene, choices }
  })
}

const SoukPlugin = makePlugin<SceneItem>(
  'najma-souk-rush',
  async ({ jsPsych, stage, item, e2e }) => {
    const talk = el('div', 'sr-talk')
    stage.append(talk)
    for (const order of item.scene.orders) {
      talk.innerHTML = ''
      talk.append(el('strong', '', order.customer), el('p', '', order.line))
      await wait(1200 + config.read_ms_per_item * order.items.length)
    }
    for (const change of item.scene.changes) {
      talk.innerHTML = ''
      talk.append(el('strong', '', change.customer), el('p', '', change.line))
      await wait(2200)
    }
    talk.remove()
    const finals = finalOrders(item.scene)
    const outcomes = []
    const base = stage.dataset['trial'] ?? ''
    let basket = 0
    for (const [customer, want] of finals) {
      basket += 1
      stage.innerHTML = ''
      stage.append(el('p', 'sr-ask', `Fill ${customer}'s basket.`))
      const grid = el('div', 'sr-grid')
      const picked = new Set<string>()
      for (const choice of item.choices[customer] ?? []) {
        const b = button(choice, `item-${slug(choice)}`, 'sr-choice')
        b.setAttribute('aria-pressed', 'false')
        b.addEventListener('click', () => {
          if (picked.has(choice)) picked.delete(choice)
          else picked.add(choice)
          b.setAttribute('aria-pressed', String(picked.has(choice)))
        })
        grid.append(b)
      }
      const done = button('Basket ready', 'basket-done')
      stage.append(grid, done)
      const started = performance.now()
      await waitForResponse(jsPsych, {
        keys: [],
        targets: [{ element: done, key: 'done' }],
        deadlineMs: 45_000,
        onReady: () => {
          markAnswer(
            stage,
            e2e,
            `clicks:${[...want.map((i) => `item-${slug(i)}`), 'basket-done'].join('|')}`,
          )
          stage.dataset['trial'] = `${base}-${String(basket)}`
        },
      })
      const right = want.filter((i) => picked.has(i)).length
      const extra = [...picked].filter((i) => !want.includes(i)).length
      outcomes.push({
        stimulus: { customer, items: want },
        response: { picked: [...picked] },
        correct: right === want.length && extra === 0,
        rt_ms: performance.now() - started,
      })
    }
    return outcomes
  },
)

export function metrics(trials: TrialRecord[]): Record<string, number> {
  const scored = trials.filter((t) => !t.practice)
  let items = 0
  for (const t of scored) {
    const want = (t.stimulus['items'] as string[] | undefined) ?? []
    const picked = (t.response?.['picked'] as string[] | undefined) ?? []
    items += want.filter((i) => picked.includes(i)).length
  }
  return {
    order_accuracy: scored.length
      ? scored.filter((t) => t.correct === true).length / scored.length
      : 0,
    items_correct: items,
  }
}

export const game: GameModule = {
  id: 'souk_rush',
  name: 'Souk Rush',
  instructions:
    'Customers will tell you their orders, and some will change their minds. Then fill each basket from memory.',
  keysHint: 'Tap the items for each basket, then Basket ready.',
  timeline({ spec, rng, e2e }) {
    const scenes = (spec.content?.['scenes'] as Scene[] | undefined) ?? []
    if (scenes.length === 0) throw new Error('Souk Rush needs orders from the server')
    return itemsToTimeline(SoukPlugin, makeItems(scenes, rng), 0, e2e)
  },
  metrics,
}
