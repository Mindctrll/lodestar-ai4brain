import { fireEvent, render, screen } from '@testing-library/react'

import type { DimensionView, GoalView, Registry } from '../api/types'
import { Goals } from './Goals'
import { NightSky } from './NightSky'

const REGISTRY = {
  dimensions: [
    {
      id: 'working_memory',
      name: 'Working memory',
      group: 'memory',
      badge: 'established',
      style: false,
    },
    {
      id: 'short_term_memory',
      name: 'Short-term memory',
      group: 'memory',
      badge: 'established',
      style: false,
    },
    { id: 'planning', name: 'Planning', group: 'reasoning', badge: 'experimental', style: false },
    {
      id: 'decision_style',
      name: 'Decision style',
      group: 'style',
      badge: 'moderate',
      style: true,
    },
  ],
  priors: { correlations: [['working_memory', 'short_term_memory', 0.4, 9000]] },
} as unknown as Registry

const view = (dim: string, sigma: number, percent: number): DimensionView => ({
  dim,
  mu: 0,
  sigma,
  n: 10,
  last_practised: null,
  percent,
  percent_low: percent - 20,
  percent_high: percent + 20,
  norms: 'simulated',
  still_learning: sigma > 0.8,
})

test('the sky blurs what Lodestar is unsure of and names what is unmeasured', () => {
  const picked: string[] = []
  render(
    <NightSky
      registry={REGISTRY}
      dims={[view('working_memory', 0.4, 60), view('short_term_memory', 1.2, 50)]}
      onSelect={(d) => picked.push(d)}
    />,
  )
  const wm = screen.getByRole('button', { name: /Working memory: 60%, likely 40% to 80%/ })
  const stm = screen.getByRole('button', { name: /Short-term memory: 50%.*still learning/ })
  expect(Number(wm.getAttribute('data-blur'))).toBeLessThan(Number(stm.getAttribute('data-blur')))
  expect(screen.getByRole('button', { name: 'Planning: not measured yet' })).toBeInTheDocument()
  expect(screen.queryByText('Decision style')).toBeNull() // styles aren't stars
  fireEvent.keyDown(wm, { key: 'Enter' })
  expect(picked).toEqual(['working_memory'])
  expect(screen.getByText(/simulated norms/)).toBeInTheDocument()
})

test('goals show the range against the target, never a bare score', () => {
  const goal = {
    goal_id: 'g1', dim: 'working_memory', name: 'Working memory', target: 15, due: '2026-11-03',
    status: 'active', range_now: 24.6, low: 30, high: 79, rounds_left: 4, met: false,
  } as GoalView // prettier-ignore
  render(<Goals goals={[goal]} />)
  expect(screen.getByText('±25')).toBeInTheDocument() // the range now, next to the aim
  expect(screen.getByText('±15')).toBeInTheDocument()
  expect(screen.getByText(/Likely 30-79% now/)).toBeInTheDocument()
  expect(screen.getByText('about 4 more rounds')).toBeInTheDocument()
  expect(
    screen.getByRole('progressbar', { name: 'Working memory goal progress' }),
  ).toBeInTheDocument()
})
