import type { Persona } from '../api/types'

/** Text to speech (docs/plan/12): the browser's own voices, or Kokoro-82M running in the
 * browser ("natural"), one voice and rate per coach. Everything spoken is also on screen as text
 * (captions). */
const STYLE: Record<Persona, { rate: number; pitch: number; kokoro: string }> = {
  willow: { rate: 0.95, pitch: 1.0, kokoro: 'af_heart' },
  spark: { rate: 1.12, pitch: 1.1, kokoro: 'am_puck' },
  sage: { rate: 1.0, pitch: 0.9, kokoro: 'bm_george' },
  buddy: { rate: 1.05, pitch: 1.05, kokoro: 'am_michael' },
}
const SPEAK_KEY = 'lodestar.voice.speak'
const VOICE_KEY = 'lodestar.voice.tts'
const KOKORO_MODEL = 'onnx-community/Kokoro-82M-v1.0-ONNX'

export type VoiceKind = 'browser' | 'natural'

export function voiceKind(): VoiceKind {
  try {
    return localStorage.getItem(VOICE_KEY) === 'natural' ? 'natural' : 'browser'
  } catch {
    return 'browser'
  }
}

export function setVoiceKind(kind: VoiceKind): void {
  try {
    localStorage.setItem(VOICE_KEY, kind)
  } catch {
    // private mode
  }
  if (kind === 'natural') void loadKokoro().catch(() => undefined)
}

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

type Kokoro = Awaited<ReturnType<typeof import('kokoro-js').KokoroTTS.from_pretrained>>
let kokoro: Promise<Kokoro> | null = null
let queue: Promise<void> = Promise.resolve()
let playing: HTMLAudioElement | null = null
let turn = 0 // stopSpeaking() moves it on, so lines already queued are dropped

/** Kokoro is a one-time download of about 90 MB (q8), cached by the browser; its own chunk. */
function loadKokoro(): Promise<Kokoro> {
  kokoro ??= import('kokoro-js')
    .then(({ KokoroTTS }) =>
      KokoroTTS.from_pretrained(KOKORO_MODEL, { dtype: 'q8', device: 'wasm' }),
    )
    .catch((e: unknown) => {
      kokoro = null
      throw e
    })
  return kokoro
}

function speakNaturally(line: string, persona: Persona): void {
  const mine = turn
  queue = queue
    .then(async () => {
      if (mine !== turn) return
      const style = STYLE[persona]
      const audio = await (
        await loadKokoro()
      ).generate(line, { voice: style.kokoro as 'af_heart', speed: style.rate })
      if (mine !== turn) return
      const url = URL.createObjectURL(audio.toBlob())
      const player = new Audio(url)
      playing = player
      await new Promise<void>((resolve) => {
        player.onended = player.onerror = () => {
          resolve()
        }
        player.play().catch(() => {
          resolve()
        })
      })
      playing = null
      URL.revokeObjectURL(url)
    })
    .catch(() => {
      // The model couldn't load or run: the browser's voice says it instead.
      speakInBrowser(line, persona)
    })
}

export function speak(text: string, persona: Persona): void {
  const line = forSpeech(text)
  if (!line) return
  if (voiceKind() === 'natural') speakNaturally(line, persona)
  else speakInBrowser(line, persona)
}

function speakInBrowser(line: string, persona: Persona): void {
  if (!canSpeak()) return
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
  turn += 1
  playing?.pause()
  playing = null
  if (canSpeak()) window.speechSynthesis.cancel()
}

/** Voice coaching in games (docs/plan/12): Lodestar reads the instructions and says "ready, go"
 * when replies are spoken. useSpeakReplies keeps the coach and the switch up to date. */
let coach: { persona: Persona; on: boolean } = { persona: 'willow', on: false }

export function setCoachVoice(persona: Persona, on: boolean): void {
  coach = { persona, on }
}

export function coachSays(text: string): void {
  if (coach.on) speak(text, coach.persona)
}
