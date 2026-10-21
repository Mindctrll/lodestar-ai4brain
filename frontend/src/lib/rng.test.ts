import { median, mulberry32, pick, randInt, shuffle } from './rng'

test('the same seed gives the same sequence', () => {
  const a = mulberry32(42)
  const b = mulberry32(42)
  expect([a(), a(), a()]).toEqual([b(), b(), b()])
})

test('helpers stay in range', () => {
  const rng = mulberry32(1)
  for (let i = 0; i < 200; i++) {
    const n = randInt(rng, 2, 5)
    expect(n).toBeGreaterThanOrEqual(2)
    expect(n).toBeLessThanOrEqual(5)
  }
  expect(['a', 'b']).toContain(pick(rng, ['a', 'b']))
  expect(shuffle(rng, [1, 2, 3, 4]).sort()).toEqual([1, 2, 3, 4])
})

test('median', () => {
  expect(median([])).toBeNull()
  expect(median([3, 1, 2])).toBe(2)
  expect(median([4, 1, 3, 2])).toBe(2.5)
})
