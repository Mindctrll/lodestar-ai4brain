import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mulberry32 } from '../lib/rng'

/** Small synthetic speech for the voice tone tests (WP3.9): voiced syllables (a few harmonics
 * under a Hann envelope) at a chosen rate, pitch spread and level, with optional pauses. Generated
 * on the fly, so no large audio files sit in the repo. */
export interface SpeechSpec {
  syllablesPerSec: number
  syllables: number
  pitchSpread?: number // semitones, up and down
  level?: number
  pauseAfter?: number[] // syllable indexes followed by a pause
  pauseSec?: number
  seed?: number
}

export const RATE = 16_000

export function synthSpeech(spec: SpeechSpec): Float32Array {
  const rng = mulberry32(spec.seed ?? 1)
  const spread = spec.pitchSpread ?? 3
  const level = spec.level ?? 0.3
  const out: number[] = new Array<number>(Math.round(0.2 * RATE)).fill(0)
  const period = 1 / spec.syllablesPerSec
  for (let s = 0; s < spec.syllables; s++) {
    const f0 = 140 * 2 ** (((rng() * 2 - 1) * spread) / 12)
    const voiced = Math.round(period * 0.85 * RATE)
    for (let i = 0; i < voiced; i++) {
      const env = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / voiced)
      const t = i / RATE
      let v = 0
      for (const [h, a] of [
        [1, 1],
        [2, 0.5],
        [3, 0.3],
        [4, 0.2],
      ] as const)
        v += a * Math.sin(2 * Math.PI * h * f0 * t)
      out.push((level * env * v) / 2)
    }
    const gap = Math.round(period * 0.15 * RATE)
    const pause = spec.pauseAfter?.includes(s) ? Math.round((spec.pauseSec ?? 0.7) * RATE) : 0
    for (let i = 0; i < gap + pause; i++) out.push(0)
  }
  for (let i = 0; i < 0.2 * RATE; i++) out.push(0)
  return Float32Array.from(out, (x) => x + (rng() - 0.5) * 0.002)
}

export const STEADY: SpeechSpec = { syllablesPerSec: 4, syllables: 12 }
export const FAST: SpeechSpec = { syllablesPerSec: 6.5, syllables: 16 }
export const SLOW: SpeechSpec = { syllablesPerSec: 2.2, syllables: 8 }
export const HESITANT: SpeechSpec = { syllablesPerSec: 3.5, syllables: 12, pauseAfter: [3, 7] }
export const FLAT_QUIET: SpeechSpec = { ...STEADY, pitchSpread: 0.2, level: 0.08 }

/** A real recording from tests/fixtures/voice (16 kHz mono 16-bit WAV, Kokoro-82M); tests run
 * from frontend/. */
export function recording(name: string): Float32Array {
  const bytes = readFileSync(resolve(process.cwd(), '../tests/fixtures/voice', `${name}.wav`))
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const n = (bytes.byteLength - 44) / 2
  return Float32Array.from({ length: n }, (_, i) => view.getInt16(44 + i * 2, true) / 0x8000)
}
