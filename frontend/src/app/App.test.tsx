import { render, screen } from '@testing-library/react'

import { App } from './App'

test('shows the app name and the practice-coach note', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Najma' })).toBeInTheDocument()
  expect(screen.getByText(/practice coach/)).toBeInTheDocument()
})
