import { listenWithTone } from '../affect/voiceTone'
import { api } from '../api/client'
import { speechEngine } from './speech'

/** Spoken answers for games (docs/plan/12, "Spoken game modes"; WP3.9): Word Burst (say the
 * words), Digits Back (say the digits), Teach Me (explain out loud). Answers are scored from the
 * transcript only. With the Voice tone switch on, the same turn also gives a tone cue
 * (affect/voiceTone.ts), sent with the round result like every cue. */

export interface SpokenAnswer {
  transcript: string
  /** Lower-case words, without "um" / "uh" and punctuation (Word Burst). */
  words: string[]
  /** Digits in the order said: "four 7 oh two" gives [4, 7, 0, 2] (Digits Back). */
  digits: number[]
}

const FILLERS = new Set(['um', 'umm', 'uh', 'uhh', 'er', 'erm', 'hmm', 'mm'])
const DIGIT_WORDS: Record<string, number> = {
  zero: 0,
  oh: 0,
  o: 0,
  one: 1,
  won: 1,
  two: 2,
  to: 2,
  too: 2,
  three: 3,
  four: 4,
  for: 4,
  five: 5,
  six: 6,
  seven: 7,
  eight: 8,
  ate: 8,
  nine: 9,
}

export function parseWords(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z']+/)
    .map((w) => w.replace(/^'+|'+$/g, ''))
    .filter((w) => w && !FILLERS.has(w))
}

export function parseDigits(text: string): number[] {
  const digits: number[] = []
  for (const token of text.toLowerCase().split(/[^a-z0-9]+/)) {
    if (/^\d+$/.test(token)) digits.push(...Array.from(token, Number))
    else if (token in DIGIT_WORDS) digits.push(DIGIT_WORDS[token] ?? 0)
  }
  return digits
}

export function toAnswer(transcript: string): SpokenAnswer {
  return { transcript, words: parseWords(transcript), digits: parseDigits(transcript) }
}

export interface AnswerTurn {
  /** End the turn now (e.g. a "Done" button) and get the answer. Safe to call twice. */
  stop(): Promise<SpokenAnswer>
  cancel(): void
}

export class MicrophoneOff extends Error {
  constructor() {
    super('To answer out loud, turn on the Microphone switch in Settings.')
  }
}

/** Start listening for one answer. Ends by itself after `maxMs`; `onAnswer` gets the result
 * whichever way it ends. Needs the Microphone switch; throws MicrophoneOff without it, so the
 * game can fall back to typing. */
export async function listenForAnswer(
  options: {
    maxMs?: number
    onInterim?: (text: string) => void
    onAnswer?: (answer: SpokenAnswer) => void
  } = {},
): Promise<AnswerTurn> {
  const consent = await api.consent()
  const on = (id: string) => consent.switches.some((s) => s.id === id && s.granted)
  if (!on('microphone')) throw new MicrophoneOff()
  const turn = await listenWithTone(
    speechEngine(),
    options.onInterim ?? (() => undefined),
    on('voice_tone'),
  )
  let result: Promise<SpokenAnswer> | null = null
  const stop = () => {
    window.clearTimeout(timer)
    result ??= turn.stop().then((text) => {
      const answer = toAnswer(text.trim())
      options.onAnswer?.(answer)
      return answer
    })
    return result
  }
  const timer = window.setTimeout(() => void stop().catch(() => undefined), options.maxMs ?? 20_000)
  return {
    stop,
    cancel: () => {
      window.clearTimeout(timer)
      turn.cancel()
    },
  }
}
