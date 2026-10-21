import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { parse } from 'yaml'

import { GAMES } from './index'

test('the registry marks exactly the games the browser can run as available', () => {
  const dir = join(import.meta.dirname, '../../../registry/games')
  const available = readdirSync(dir)
    .filter((f) => f.endsWith('.yaml'))
    .map((f) => parse(readFileSync(join(dir, f), 'utf8')) as { id: string; available?: boolean })
    .filter((g) => g.available === true)
    .map((g) => g.id)
    .sort()
  expect(available).toEqual(Object.keys(GAMES).sort())
})
