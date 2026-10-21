import type { Persona } from '../api/types'

/** Text to speech (docs/plan/12): the browser's own voices, one rate and pitch per coach.
 * Everything spoken is also on screen as text (captions). */
const STYLE: Record<Persona, { rate: number; pitch: number }> = {
  zitouna: { rate: 0.95, pitch: 1.0 },
  barq: { rate: 1.12, pitch: 1.1 },
  hikma: { rate: 1.0, pitch: 0.9 },
  sahbi: { rate: 1.05, pitch: 1.05 },
}
const SPEAK_KEY = 'najma.voice.speak'

/** What a person should hear: citations like [F1] or [D1, F2] are for the screen. */
export function forSpeech(text: string): string {
  return text
    .replace(/\s*\[[FDKM]\d+(?:\s*,\s*[FDKM]\d+)*\]/g, '')
    .replace(/±/g, 'plus or minus ')
    .replace(/\s+/g, ' ')
    .trim()
}

export function speakReplies(): boolean {
  try {
    return localStorage.getItem(SPEAK_KEY) === 'on'
  } catch {
    return false
  }
}

export function setSpeakReplies(on: boolean): void {
  try {
    localStorage.setItem(SPEAK_KEY, on ? 'on' : 'off')
  } catch {
    // private mode
  }
}

export function canSpeak(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window
}

export function speak(text: string, persona: Persona): void {
  if (!canSpeak()) return
  const line = forSpeech(text)
  if (!line) return
  const utterance = new SpeechSynthesisUtterance(line)
  const style = STYLE[persona]
  utterance.rate = style.rate
  utterance.pitch = style.pitch
  utterance.lang = 'en-US'
  const english = window.speechSynthesis.getVoices().filter((v) => v.lang.startsWith('en'))
  const voice = english[Object.keys(STYLE).indexOf(persona) % Math.max(1, english.length)]
  if (voice) utterance.voice = voice
  window.speechSynthesis.speak(utterance)
}

export function stopSpeaking(): void {
  if (canSpeak()) window.speechSynthesis.cancel()
}
