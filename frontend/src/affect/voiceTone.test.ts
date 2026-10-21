import { beforeEach, describe, expect, it } from 'vitest'

import {
  FAST,
  FLAT_QUIET,
  HESITANT,
  STEADY,
  recording,
  SLOW,
  synthSpeech,
  type SpeechSpec,
} from '../test/speechFixtures'
import {
  BASELINE_N,
  finishTurn,
  framesFromSamples,
  hesitationRate,
  readBaseline,
  TONE_WORKLET,
  toneFeatures,
  type ToneFeatures,
} from './voiceTone'

function features(spec: SpeechSpec, transcript = 'I think it was the blue one'): ToneFeatures {
  const f = toneFeatures(framesFromSamples(synthSpeech(spec)), transcript)
  if (!f) throw new Error('no speech found')
  return f
}

describe('tone features (WP3.9)', () => {
  it('measures speech rate from syllable-like energy peaks', () => {
    for (const spec of [SLOW, STEADY, FAST]) {
      const rate = features(spec).speech_rate
      expect(rate).toBeGreaterThan(spec.syllablesPerSec * 0.8)
      expect(rate).toBeLessThan(spec.syllablesPerSec * 1.2)
    }
  })

  it('finds pauses over 300 ms in hesitant speech only', () => {
    expect(features(HESITANT).pause_ratio).toBeGreaterThan(0.2)
    for (const spec of [SLOW, STEADY, FAST]) expect(features(spec).pause_ratio).toBe(0)
  })

  it('reads pitch variability and loudness', () => {
    const steady = features(STEADY)
    const flat = features(FLAT_QUIET)
    expect(steady.pitch_sd).toBeGreaterThan(1)
    expect(flat.pitch_sd).toBeLessThan(0.5)
    expect(flat.loudness_db).toBeLessThan(steady.loudness_db - 6)
  })

  it('counts hesitation words in the transcript', () => {
    expect(hesitationRate('um so I think uh it was um the blue one')).toBeCloseTo(3 / 11)
    expect(hesitationRate('the umbrella is here')).toBe(0)
  })

  it('works on a real recording', () => {
    const f = toneFeatures(framesFromSamples(recording('i_slept_badly')), 'I slept like four hours')
    expect(f?.speech_rate).toBeGreaterThan(2)
    expect(f?.speech_rate).toBeLessThan(9)
    expect(f?.pitch_sd).toBeGreaterThan(0.5)
  })
})

describe('the AudioWorklet', () => {
  it('runs the same analysis on the audio thread and posts only two numbers per frame', () => {
    const posted: unknown[] = []
    type Node = { process(inputs: Float32Array[][]): boolean }
    let Processor: (new () => Node) | undefined
    class Base {
      port = { postMessage: (m: unknown) => posted.push(m) }
    }
    // The worklet ships as source text; run that exact text with the audio thread's globals.
    // eslint-disable-next-line @typescript-eslint/no-implied-eval
    const load = new Function(
      'AudioWorkletProcessor',
      'registerProcessor',
      'sampleRate',
      TONE_WORKLET,
    ) as (
      base: unknown,
      register: (name: string, ctor: new () => Node) => void,
      rate: number,
    ) => void
    load(Base, (_: string, ctor: new () => Node) => (Processor = ctor), 16_000)
    if (!Processor) throw new Error('worklet did not register')
    const node = new Processor()
    const samples = synthSpeech(STEADY)
    for (let at = 0; at + 128 <= samples.length; at += 128)
      node.process([[samples.subarray(at, at + 128)]])
    expect(posted.every((m) => Array.isArray(m) && m.length === 2)).toBe(true)
    const f = toneFeatures(posted as [number, number][], '')
    expect(f?.speech_rate).toBeGreaterThan(STEADY.syllablesPerSec * 0.8)
    expect(f?.speech_rate).toBeLessThan(STEADY.syllablesPerSec * 1.2)
  })
})

describe('voice_strain_cue against the user own baseline', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('stays silent for the first ten utterances, then reads change from them', () => {
    for (let seed = 1; seed <= BASELINE_N; seed++) {
      const frames = framesFromSamples(synthSpeech({ ...STEADY, seed }))
      expect(finishTurn(frames, 'I think it was the blue one')).toBeNull()
    }
    expect(readBaseline().n).toBe(BASELINE_N)

    const cue = (spec: SpeechSpec, transcript = 'I think it was the blue one') =>
      finishTurn(framesFromSamples(synthSpeech({ ...spec, seed: 99 })), transcript) ?? -1
    const steady = cue(STEADY)
    expect(steady).toBeGreaterThanOrEqual(0)
    expect(steady).toBeLessThan(0.2)
    expect(cue(HESITANT, 'um so I think uh it was um the blue one')).toBeGreaterThan(0.6)
    expect(cue(SLOW)).toBeGreaterThan(steady)
    expect(cue(FAST)).toBeGreaterThan(steady)
    expect(readBaseline().n).toBe(BASELINE_N) // the baseline is the first ten only
  }, 20_000) // ten utterances of pitch analysis
})
