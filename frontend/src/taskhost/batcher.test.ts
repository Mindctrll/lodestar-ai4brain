import type { TrialEvent } from '../api/types'
import { TrialBatcher } from './batcher'

const trial = (i: number): TrialEvent => ({
  trial_id: `t${String(i)}`,
  round_id: 'r',
  session_id: 's',
  game_id: 'echo',
  level: 0.4,
  trial_index: i,
  practice: false,
  stimulus: {},
  hint_level: 0,
  ts: new Date().toISOString(),
})

test('sends full batches and the rest on close', async () => {
  const sent: TrialEvent[][] = []
  const batcher = new TrialBatcher(
    async (b) => {
      sent.push(b)
      return Promise.resolve()
    },
    3,
    60_000,
  )
  for (let i = 0; i < 7; i++) batcher.add(trial(i))
  await batcher.close()
  expect(sent.map((b) => b.length)).toEqual([3, 3, 1])
})

test('retries a failed batch', async () => {
  let calls = 0
  const batcher = new TrialBatcher(
    async () => {
      calls++
      if (calls === 1) throw new Error('offline')
      return Promise.resolve()
    },
    10,
    60_000,
    2,
  )
  batcher.add(trial(0))
  await batcher.close()
  expect(calls).toBe(2)
  expect(batcher.pending).toBe(0)
})
