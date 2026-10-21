import { render, screen } from '@testing-library/react'

import { App } from './App'

test('a first visit starts with the welcome and the practice-coach note', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Welcome to Najma' })).toBeInTheDocument()
  expect(screen.getByText(/practice coach/)).toBeInTheDocument()
})
