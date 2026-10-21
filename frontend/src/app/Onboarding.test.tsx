import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { Onboarding } from './Onboarding'

const NOTICE = {
  version: 'test',
  age_minimum: 18,
  switches: [
    { id: 'core', title: 'Core practice data', required: true, default: true, plain: 'Needed.' },
    { id: 'camera', title: 'Camera', required: false, default: false, plain: 'Off.' },
  ],
}

function stubApi() {
  const calls: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const raw = typeof init?.body === 'string' ? init.body : null
      calls.push({ url, body: raw ? (JSON.parse(raw) as unknown) : null })
      const payload = url.endsWith('/registry')
        ? { consent: NOTICE }
        : { user_id: 'u1', token: 'token-1' }
      return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }))
    }),
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

test('under 18: stops, and nothing is sent', async () => {
  const calls = stubApi()
  render(<Onboarding onDone={() => undefined} />)
  fireEvent.click(screen.getByRole('button', { name: 'Get started' }))
  fireEvent.click(await screen.findByRole('button', { name: "I'm younger" }))
  expect(screen.getByText(/Nothing about you has been stored/)).toBeInTheDocument()
  expect(calls.filter((c) => c.url.endsWith('/users'))).toEqual([])
})

test('core is locked on; the choices and coach are sent once, at the end', async () => {
  const calls = stubApi()
  let done = false
  render(
    <Onboarding
      onDone={() => {
        done = true
      }}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Get started' }))
  fireEvent.click(await screen.findByRole('button', { name: "I'm 18 or older" }))
  const core = await screen.findByRole('checkbox', { name: /Core practice data/ })
  expect(core).toBeChecked()
  expect(core).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
  fireEvent.click(screen.getByRole('radio', { name: /Barq/ }))
  fireEvent.click(screen.getByRole('button', { name: "Let's start" }))
  await waitFor(() => {
    expect(done).toBe(true)
  })
  const signup = calls.filter((c) => c.url.endsWith('/users'))
  expect(signup).toHaveLength(1)
  expect(signup[0]?.body).toMatchObject({
    age_confirmed: true,
    persona: 'barq',
    consent: { core: true, camera: false },
  })
})
