import { api } from '../api/client'
import { button } from '../taskhost/plugin'
import { listen, speechEngine, type Listening } from './speech'

/** Answer a game out loud (docs/plan/12, spoken game modes): a "Say it" button for games whose
 * registry `modalities` include `voice`. Tap, speak, tap again; the transcript goes to `onText`.
 * Answers are scored from the transcript only. Typing always works too. */
export function voiceAnswer(
  label: string,
  onText: (text: string) => void,
): { button: HTMLButtonElement; cancel: () => void } {
  const say = button(label, 'voice-answer')
  let turn: Listening | null = null
  const reset = (title = '') => {
    say.textContent = label
    say.disabled = false
    say.title = title
  }
  say.onclick = async () => {
    if (turn) {
      const current = turn
      turn = null
      say.textContent = 'Working it out…'
      say.disabled = true
      try {
        const text = (await current.stop()).trim()
        if (text) onText(text)
        reset(text ? '' : "I didn't catch that. Try again?")
      } catch (e) {
        reset(e instanceof Error ? e.message : String(e))
      }
      return
    }
    try {
      const consent = await api.consent()
      if (!consent.switches.some((s) => s.id === 'microphone' && s.granted)) {
        reset('Turn on the microphone switch in Settings first.')
        say.textContent = 'Microphone is off'
        say.disabled = true
        return
      }
      turn = await listen(speechEngine(), () => undefined)
      say.textContent = 'Done talking'
    } catch (e) {
      reset(e instanceof Error ? e.message : String(e))
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
