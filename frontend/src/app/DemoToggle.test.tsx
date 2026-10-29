import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { getToken } from '../api/client'
import { DemoToggle } from './DemoToggle'

test('the demo switch signs in as Alex and back to your own data', async () => {
  localStorage.setItem('lodestar.token', 'mine')
  const reload = vi.fn()
  Object.defineProperty(window, 'location', { value: { reload }, writable: true })
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ user_id: 'u', token: 'alex' }), { status: 200 }),
      ),
    ),
  )

  const { unmount } = render(<DemoToggle variant="rail" />)
  fireEvent.click(screen.getByRole('switch', { name: 'Demo person' }))
  await waitFor(() => {
    expect(reload).toHaveBeenCalledTimes(1)
  })
  expect(getToken()).toBe('alex')
  unmount()

  render(<DemoToggle variant="rail" />)
  const on = screen.getByRole('switch', { name: 'Demo person' })
  expect(on).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(on)
  await waitFor(() => {
    expect(reload).toHaveBeenCalledTimes(2)
  })
  expect(getToken()).toBe('mine')
  vi.unstubAllGlobals()
})
