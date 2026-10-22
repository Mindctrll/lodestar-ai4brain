import { listen, type Listening, type SpeechEngine } from '../voice/speech'
import { recordCue, signalStarted, signalStopped } from './cues'

/** Voice tone cues (docs/plan/12, "Optional voice tone"; WP3.9). While the user speaks to Lodestar or
 * answers a spoken game, and only with the Voice tone switch on, an AudioWorklet turns the
 * microphone's samples into two numbers per 20 ms (loudness and pitch); the samples themselves
 * never leave the audio thread. At the end of the utterance those frames and the transcript give
 * five features, compared with this user's own first ten utterances, and one coarse
 * `voice_strain_cue`. Features and baseline stay in this browser; only the cue is sent. */

export const FRAME_SEC = 0.02 // hop between analysis windows
const WINDOW_SEC = 0.04
const RATE = 16_000
const PAUSE_FRAMES = 15 // 300 ms
const BASELINE_KEY = 'lodestar.voice.baseline'
export const BASELINE_N = 10

/** [loudness (RMS), pitch in Hz or 0 when unvoiced] for one 40 ms window. */
export type Frame = [number, number]

/** Self-contained on purpose: its source text also runs inside the AudioWorklet. Pitch by
 * normalised autocorrelation (70 to 400 Hz), taking the shortest strong lag to avoid octave
 * errors. */
export function analyseWindow(x: Float32Array, rate: number): [number, number] {
  let energy = 0
  for (let i = 0; i < x.length; i++) energy += (x[i] ?? 0) * (x[i] ?? 0)
  const rms = Math.sqrt(energy / Math.max(1, x.length))
  if (rms < 0.002) return [rms, 0]
  const minLag = Math.floor(rate / 400)
  const maxLag = Math.min(Math.floor(rate / 70), x.length - 1)
  const r: number[] = []
  let best = 0
  for (let lag = minLag; lag <= maxLag; lag++) {
    let num = 0
    let a = 0
    let b = 0
    for (let i = 0; i + lag < x.length; i++) {
      const p = x[i] ?? 0
      const q = x[i + lag] ?? 0
      num += p * q
      a += p * p
      b += q * q
    }
    const v = a > 0 && b > 0 ? num / Math.sqrt(a * b) : 0
    r.push(v)
    if (v > best) best = v
  }
  if (best < 0.6) return [rms, 0]
  for (let k = 1; k < r.length - 1; k++) {
    const v = r[k] ?? 0
    if (v >= 0.9 * best && v >= (r[k - 1] ?? 0) && v >= (r[k + 1] ?? 0))
      return [rms, rate / (minLag + k)]
  }
  return [rms, 0]
}

/** The same windows as the worklet, for recordings (tests use this). */
export function framesFromSamples(samples: Float32Array, rate = RATE): Frame[] {
  const size = Math.round(rate * WINDOW_SEC)
  const hop = Math.round(rate * FRAME_SEC)
  const frames: Frame[] = []
  for (let at = 0; at + size <= samples.length; at += hop)
    frames.push(analyseWindow(samples.subarray(at, at + size), rate))
  return frames
}

export const TONE_WORKLET = `const analyse = ${analyseWindow.toString()};
class LodestarTone extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buf = new Float32Array(Math.round(sampleRate * ${String(WINDOW_SEC)}))
    this.hop = Math.round(sampleRate * ${String(FRAME_SEC)})
    this.since = 0
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (!ch) return true
    this.buf.copyWithin(0, ch.length)
    this.buf.set(ch, this.buf.length - ch.length)
    this.since += ch.length
    if (this.since >= this.hop) {
      this.since -= this.hop
      this.port.postMessage(analyse(this.buf, sampleRate))
    }
    return true
  }
}
registerProcessor('lodestar-tone', LodestarTone)`

export interface ToneFeatures {
  speech_rate: number // syllable-like energy peaks per second of speaking
  pause_ratio: number // share of the utterance in pauses over 300 ms
  pitch_sd: number // semitones
  loudness_db: number
  loudness_slope: number // dB per second
  hesitation_rate: number // "um", "uh" per word of the transcript
}
type Key = keyof ToneFeatures
const KEYS: Key[] = [
  'speech_rate',
  'pause_ratio',
  'pitch_sd',
  'loudness_db',
  'loudness_slope',
  'hesitation_rate',
]

const HESITATION = /\b(u+m+|u+h+|e+r+m*|h+m+)\b/gi

export function hesitationRate(transcript: string): number {
  const words = transcript.split(/\s+/).filter(Boolean).length
  return words ? (transcript.match(HESITATION)?.length ?? 0) / words : 0
}

function mean(xs: number[]): number {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0
}

function sd(xs: number[]): number {
  const m = mean(xs)
  return Math.sqrt(mean(xs.map((x) => (x - m) ** 2)))
}

/** The five features of one utterance; null when there was too little speech. */
export function toneFeatures(frames: Frame[], transcript: string): ToneFeatures | null {
  const loud = frames.map(([rms]) => rms)
  const sorted = [...loud].sort((a, b) => a - b)
  const threshold = Math.max(0.003, 0.15 * (sorted[Math.floor(0.95 * (sorted.length - 1))] ?? 0))
  const speech = loud.map((v) => v > threshold)
  const first = speech.indexOf(true)
  const last = speech.lastIndexOf(true)
  if (first < 0 || speech.filter(Boolean).length < 10) return null

  let pauseFrames = 0
  let run = 0
  for (let i = first; i <= last + 1; i++) {
    if (i <= last && !speech[i]) run += 1
    else {
      if (run >= PAUSE_FRAMES) pauseFrames += run
      run = 0
    }
  }
  const span = last - first + 1

  // Syllable-like peaks: the smoothed loudness halves after a peak, then at least doubles from
  // its lowest point while above the threshold.
  let peaks = 0
  let armed = true
  let peak = 0
  let trough = 0
  for (let i = first; i <= last; i++) {
    const e = mean(loud.slice(Math.max(0, i - 1), i + 2))
    if (armed) {
      trough = Math.min(trough, e)
      if (e > threshold && e > 2 * trough) {
        peaks += 1
        armed = false
        peak = e
      }
    } else {
      peak = Math.max(peak, e)
      if (e < 0.5 * peak) {
        armed = true
        trough = e
      }
    }
  }

  const voiced: number[] = []
  const db: number[] = []
  const t: number[] = []
  for (let i = first; i <= last; i++) {
    const [rms, f0] = frames[i] ?? [0, 0]
    if (!speech[i]) continue
    if (f0 > 0) voiced.push(12 * Math.log2(f0 / 100))
    db.push(20 * Math.log10(rms))
    t.push(i * FRAME_SEC)
  }
  const tm = mean(t)
  const dm = mean(db)
  const varT = t.reduce((a, x) => a + (x - tm) ** 2, 0)
  const slope = varT > 0 ? t.reduce((a, x, k) => a + (x - tm) * ((db[k] ?? 0) - dm), 0) / varT : 0

  return {
    speech_rate: peaks / Math.max(FRAME_SEC, (span - pauseFrames) * FRAME_SEC),
    pause_ratio: pauseFrames / span,
    pitch_sd: sd(voiced),
    loudness_db: dm,
    loudness_slope: slope,
    hesitation_rate: hesitationRate(transcript),
  }
}

/** The user's own first ten utterances (sums and sums of squares), kept in this browser only. */
export interface Baseline {
  n: number
  sum: Record<Key, number>
  sq: Record<Key, number>
}

function emptyBaseline(): Baseline {
  const zero = () => Object.fromEntries(KEYS.map((k) => [k, 0])) as Record<Key, number>
  return { n: 0, sum: zero(), sq: zero() }
}

export function readBaseline(): Baseline {
  try {
    const raw = localStorage.getItem(BASELINE_KEY)
    if (raw) return JSON.parse(raw) as Baseline
  } catch {
    // no storage: start again
  }
  return emptyBaseline()
}

function saveBaseline(b: Baseline): void {
  try {
    localStorage.setItem(BASELINE_KEY, JSON.stringify(b))
  } catch {
    // private mode: the baseline lasts for this page only
  }
}

export function forgetBaseline(): void {
  try {
    localStorage.removeItem(BASELINE_KEY)
  } catch {
    // nothing stored
  }
}

/** Smallest spread used for a z-score, so a very steady baseline doesn't overreact. */
const FLOOR: Record<Key, number> = {
  speech_rate: 0.5,
  pause_ratio: 0.05,
  pitch_sd: 0.5,
  loudness_db: 3,
  loudness_slope: 3,
  hesitation_rate: 0.05,
}
/** Which way counts as strain: rushing or slowing, more pauses, a flatter voice, dropping
 * loudness, more "um". */
const DIRECTION: Record<Key, 'both' | 1 | -1> = {
  speech_rate: 'both',
  pause_ratio: 1,
  pitch_sd: -1,
  loudness_db: -1,
  loudness_slope: -1,
  hesitation_rate: 1,
}

/** 0 to 1 against the user's own baseline; null until the baseline has ten utterances. */
export function voiceStrainCue(f: ToneFeatures, b: Baseline): number | null {
  if (b.n < BASELINE_N) return null
  const parts = KEYS.map((k) => {
    const m = b.sum[k] / b.n
    const spread = Math.max(FLOOR[k], Math.sqrt(Math.max(0, b.sq[k] / b.n - m * m)))
    const z = (f[k] - m) / spread
    const d = DIRECTION[k]
    return Math.max(0, d === 'both' ? Math.abs(z) - 1 : d * z)
  })
  return Math.min(1, mean(parts) / 2)
}

/** End of an utterance: features, the baseline (first ten only), and the coarse cue. */
export function finishTurn(frames: Frame[], transcript: string): number | null {
  const f = toneFeatures(frames, transcript)
  if (!f) return null
  const b = readBaseline()
  if (b.n < BASELINE_N) {
    b.n += 1
    for (const k of KEYS) {
      b.sum[k] += f[k]
      b.sq[k] += f[k] * f[k]
    }
    saveBaseline(b)
    return null
  }
  const cue = voiceStrainCue(f, b)
  if (cue !== null) recordCue('voice', cue)
  return cue
}

export interface ToneTurn {
  finish(transcript: string): Promise<number | null>
  cancel(): void
}

/** Start reading tone from the microphone for one utterance. */
export async function startVoiceTone(): Promise<ToneTurn> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } })
  const context = new AudioContext({ sampleRate: RATE })
  const frames: Frame[] = []
  const close = async () => {
    for (const track of stream.getTracks()) track.stop()
    signalStopped('voice')
    if (context.state !== 'closed') await context.close()
  }
  try {
    const module = URL.createObjectURL(new Blob([TONE_WORKLET], { type: 'application/javascript' }))
    await context.audioWorklet.addModule(module)
    URL.revokeObjectURL(module)
    const node = new AudioWorkletNode(context, 'lodestar-tone')
    node.port.onmessage = (e: MessageEvent<Frame>) => {
      frames.push(e.data)
    }
    const silent = context.createGain()
    silent.gain.value = 0
    context.createMediaStreamSource(stream).connect(node)
    node.connect(silent)
    silent.connect(context.destination)
  } catch (e) {
    await close()
    throw e
  }
  signalStarted('voice', () => void close())
  return {
    finish: async (transcript) => {
      await close()
      return finishTurn(frames, transcript)
    },
    cancel: () => void close(),
  }
}

/** `listen()` plus tone cues when `tone` is on (the Voice tone switch). If tone can't start,
 * listening goes on without it. */
export async function listenWithTone(
  engine: SpeechEngine,
  onInterim: (text: string) => void,
  tone: boolean,
  onQuiet?: () => void,
): Promise<Listening> {
  const toneTurn = tone ? await startVoiceTone().catch(() => null) : null
  let inner: Listening
  try {
    inner = await listen(engine, onInterim, onQuiet)
  } catch (e) {
    toneTurn?.cancel()
    throw e
  }
  return {
    stop: async () => {
      let text: string
      try {
        text = await inner.stop()
      } catch (e) {
        toneTurn?.cancel()
        throw e
      }
      await toneTurn?.finish(text)
      return text
    },
    cancel: () => {
      inner.cancel()
      toneTurn?.cancel()
    },
  }
}
