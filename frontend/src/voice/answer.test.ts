import { voiceAnswer } from './answer'
import { listenForAnswer, MicrophoneOff, toAnswer } from './spokenAnswer'

vi.mock('./spokenAnswer', async (original) => ({
  ...(await original<typeof import('./spokenAnswer')>()),
  listenForAnswer: vi.fn(),
}))

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

test('a spoken answer is added to the same text box', async () => {
  vi.mocked(listenForAnswer).mockImplementation((options = {}) =>
    Promise.resolve({
      stop: () => {
        const answer = toAnswer('um four 7 oh')
        options.onAnswer?.(answer)
        return Promise.resolve(answer)
      },
      cancel: vi.fn(),
    }),
  )
  const input = document.createElement('textarea')
  input.value = '9'
  const typed = vi.fn()
  input.addEventListener('input', typed)
  const say = voiceAnswer(input, 'Say it', (a) => a.digits.join(''))
  say.button.click()
  await flush()
  expect(say.button.textContent).toBe('Done talking')
  say.button.click()
  await flush()
  expect(input.value).toBe('9 470')
  expect(typed).toHaveBeenCalled()
  expect(say.button.textContent).toBe('Say it')
})

test('with the microphone off, the button says so and typing still works', async () => {
  vi.mocked(listenForAnswer).mockRejectedValue(new MicrophoneOff())
  const input = document.createElement('input')
  const say = voiceAnswer(input, 'Say it', (a) => a.transcript)
  say.button.click()
  await flush()
  expect(say.button.disabled).toBe(true)
  expect(say.button.textContent).toMatch(/turn on the Microphone switch/)
  expect(input.disabled).toBe(false)
})
