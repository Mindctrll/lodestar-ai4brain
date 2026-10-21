import { button } from '../taskhost/plugin'
import { listenForAnswer, MicrophoneOff, type AnswerTurn, type SpokenAnswer } from './spokenAnswer'

/** Answer a game out loud (docs/plan/12, spoken game modes): a "Say it" button for games whose
 * registry `modalities` include `voice`. Tap, speak, tap again (or wait `maxMs`); `pick` turns the
 * answer into text that is added to `input`, so the game scores it like typing. Typing always
 * works too; with the Microphone switch off the button just says so. */
export function voiceAnswer(
  input: HTMLInputElement | HTMLTextAreaElement,
  label: string,
  pick: (answer: SpokenAnswer) => string,
  maxMs = 20_000,
): { button: HTMLButtonElement; cancel: () => void } {
  const say = button(label, 'voice-answer')
  let turn: AnswerTurn | null = null
  const reset = (title = '') => {
    turn = null
    say.textContent = label
    say.disabled = false
    say.title = title
  }
  const fill = (answer: SpokenAnswer) => {
    const text = pick(answer)
    if (text) {
      input.value = `${input.value} ${text}`.trim()
      input.dispatchEvent(new Event('input'))
    }
    reset(text ? '' : "I didn't catch that. Try again?")
  }
  say.onclick = async () => {
    if (turn) {
      const current = turn
      say.textContent = 'Working it out…'
      say.disabled = true
      await current.stop().catch((e: unknown) => {
        reset(e instanceof Error ? e.message : String(e))
      })
      return
    }
    try {
      turn = await listenForAnswer({ maxMs, onAnswer: fill })
      say.textContent = 'Done talking'
    } catch (e) {
      reset(e instanceof Error ? e.message : String(e))
      if (e instanceof MicrophoneOff) {
        say.textContent = e.message
        say.disabled = true
      }
    }
  }
  return {
    button: say,
    cancel: () => {
      turn?.cancel()
      turn = null
    },
  }
}
