import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { Orb } from './Orb'
import { listen } from './speech'
import { maskedKey, saveWakeSetup, startWake } from './wake'

vi.mock('./speech', () => ({
  speechEngine: () => 'browser',
  listen: vi.fn(() => Promise.resolve({ stop: () => Promise.resolve('hello'), cancel: vi.fn() })),
}))
vi.mock('./wake', async (original) => ({
  ...(await original<typeof import('./wake')>()),
  startWake: vi.fn(),
}))

const KEY = 'pv-access-key-secret-1234'
const sent: string[] = []

beforeEach(() => {
  sent.length = 0
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      sent.push(url, JSON.stringify(init ?? {}))
      const consent = { version: 't', switches: [{ id: 'microphone', granted: true }] }
      return Promise.resolve(new Response(JSON.stringify(consent), { status: 200 }))
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.mocked(startWake).mockReset()
  vi.mocked(listen).mockClear()
  localStorage.clear()
})

test('without a wake word set up, tap-to-talk works as before', async () => {
  const heard = vi.fn()
  render(<Orb onTranscript={heard} />)
  const orb = screen.getByRole('button', { name: 'Tap to talk (Alt+V)' })
  fireEvent.click(orb)
  await screen.findByRole('button', { name: 'Listening. Tap to send' })
  fireEvent.click(screen.getByRole('button', { name: 'Listening. Tap to send' }))
  await waitFor(() => {
    expect(heard).toHaveBeenCalledWith('hello')
  })
  expect(startWake).not.toHaveBeenCalled()
})

test('if the wake word fails to start, tap-to-talk still works', async () => {
  saveWakeSetup({ accessKey: KEY, keyword: 'cHBu' })
  vi.mocked(startWake).mockRejectedValue(new Error('activation refused'))
  render(<Orb onTranscript={() => undefined} />)
  expect(await screen.findByTestId('wake-off')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Tap to talk (Alt+V)' }))
  await screen.findByRole('button', { name: 'Listening. Tap to send' })
})

test('"Hey Lodestar" starts a hands-free turn; the key never goes to the server', async () => {
  saveWakeSetup({ accessKey: KEY, keyword: 'cHBu' })
  let wake: () => void = () => undefined
  vi.mocked(startWake).mockImplementation((_setup, onWake) => {
    wake = onWake
    return Promise.resolve(() => undefined)
  })
  render(<Orb onTranscript={() => undefined} />)
  await screen.findByRole('button', { name: 'Say "Hey Lodestar" or tap to talk (Alt+V)' })
  wake()
  await screen.findByRole('button', { name: 'Listening. Tap to send' })
  // A hands-free turn ends itself after a pause.
  expect(vi.mocked(listen).mock.calls[0]?.[2]).toBeTypeOf('function')
  expect(sent.length).toBeGreaterThan(0)
  expect(sent.join(' ')).not.toContain(KEY)
  expect(maskedKey(KEY)).toBe('••••1234')
})
