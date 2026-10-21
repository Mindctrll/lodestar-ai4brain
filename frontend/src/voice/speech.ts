import { API_BASE, ApiError, getToken } from '../api/client'

/** Speech to text (docs/plan/12, Voice stack). "browser" uses the browser's own recognition,
 * which may send audio to its maker (Chrome: Google). "private" records here, converts to 16 kHz
 * WAV, and transcribes on Najma's server, where the audio is not kept. "device" runs Whisper in
 * this browser (Transformers.js), so the audio never leaves the device. */
export type SpeechEngine = 'browser' | 'private' | 'device'

const ENGINE_KEY = 'najma.voice.engine'
const RATE = 16_000
const WHISPER_MODEL = 'onnx-community/whisper-base.en'
// A turn started by the wake word ends by itself after this much quiet once speech has begun.
const QUIET_MS = 1_200
const QUIET_RMS = 0.01
const TAP_WORKLET = `class Tap extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (channel) this.port.postMessage(channel.slice(0))
    return true
  }
}
registerProcessor('najma-tap', Tap)`

interface RecognitionResult {
  isFinal: boolean
  0: { transcript: string }
}
interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((e: { results: ArrayLike<RecognitionResult> }) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}
type RecognitionCtor = new () => Recognition

function recognitionCtor(): RecognitionCtor | undefined {
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor
    webkitSpeechRecognition?: RecognitionCtor
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition
}

export function browserRecognitionAvailable(): boolean {
  return recognitionCtor() !== undefined
}

export function speechEngine(): SpeechEngine {
  try {
    const saved = localStorage.getItem(ENGINE_KEY)
    if (saved === 'browser' || saved === 'private' || saved === 'device') return saved
  } catch {
    // no storage: fall through
  }
  return browserRecognitionAvailable() ? 'browser' : 'private'
}

export function setSpeechEngine(engine: SpeechEngine): void {
  try {
    localStorage.setItem(ENGINE_KEY, engine)
  } catch {
    // private mode: the choice lasts for this page only
  }
  if (engine === 'device') void loadWhisper().catch(() => undefined)
}

type Transcriber = (audio: Float32Array) => Promise<string>
let whisper: Promise<Transcriber> | null = null

/** Whisper base.en in the browser: a one-time download of about 80 MB (q8), cached by the
 * browser, in its own chunk. */
export function loadWhisper(): Promise<Transcriber> {
  whisper ??= import('@huggingface/transformers')
    .then(async ({ pipeline }) => {
      const asr = await pipeline('automatic-speech-recognition', WHISPER_MODEL, { dtype: 'q8' })
      return async (audio: Float32Array) => {
        const out = (await asr(audio)) as { text: string } | { text: string }[]
        return (Array.isArray(out) ? (out[0]?.text ?? '') : out.text).trim()
      }
    })
    .catch((e: unknown) => {
      whisper = null
      throw e
    })
  return whisper
}

/** 16-bit PCM WAV, mono: the only format the private engine accepts. */
export function encodeWav(samples: Float32Array, rate = RATE): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const text = (at: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(at + i, s.charCodeAt(i))
  }
  text(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, rate, true)
  view.setUint32(28, rate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  text(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  samples.forEach((s, i) => {
    const x = Math.max(-1, Math.min(1, s))
    view.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true)
  })
  return buffer
}

/** A listening turn: `stop()` ends it and resolves with what was said. */
export interface Listening {
  stop(): Promise<string>
  cancel(): void
}

function listenInBrowser(onInterim: (text: string) => void, onQuiet?: () => void): Listening {
  const Ctor = recognitionCtor()
  if (!Ctor)
    throw new Error("This browser can't recognise speech; choose private voice in Settings.")
  const rec = new Ctor()
  rec.lang = 'en-US'
  rec.interimResults = true
  rec.continuous = false
  let finalText = ''
  let settle: ((text: string) => void) | null = null
  let fail: ((e: Error) => void) | null = null
  const done = new Promise<string>((resolve, reject) => {
    settle = resolve
    fail = reject
  })
  rec.onresult = (e) => {
    let interim = ''
    for (const r of Array.from(e.results)) {
      if (r.isFinal) finalText += r[0].transcript
      else interim += r[0].transcript
    }
    onInterim((finalText + interim).trim())
  }
  rec.onerror = (e) =>
    fail?.(new Error(e.error === 'not-allowed' ? 'Microphone blocked by the browser.' : e.error))
  rec.onend = () => {
    settle?.(finalText.trim())
    onQuiet?.() // the browser stops by itself after a pause
  }
  rec.start()
  return {
    stop: () => {
      rec.stop()
      return done
    },
    cancel: () => {
      rec.abort()
    },
  }
}

/** Record 16 kHz mono samples here; nothing leaves the page until `stop()` hands them over. */
async function record(onQuiet?: () => void): Promise<{
  stop: () => Promise<Float32Array>
  cancel: () => void
}> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } })
  const context = new AudioContext({ sampleRate: RATE })
  const source = context.createMediaStreamSource(stream)
  const chunks: Float32Array[] = []
  // A tiny worklet that only copies the microphone's samples out; nothing is processed.
  const module = URL.createObjectURL(new Blob([TAP_WORKLET], { type: 'application/javascript' }))
  await context.audioWorklet.addModule(module)
  URL.revokeObjectURL(module)
  const tap = new AudioWorkletNode(context, 'najma-tap')
  let spoke = false
  let quietSince = 0
  tap.port.onmessage = (e: MessageEvent<Float32Array>) => {
    chunks.push(e.data)
    if (!onQuiet) return
    const loud = Math.sqrt(e.data.reduce((n, x) => n + x * x, 0) / e.data.length) > QUIET_RMS
    const now = performance.now()
    if (loud) {
      spoke = true
      quietSince = now
    } else if (spoke && now - quietSince > QUIET_MS) {
      spoke = false
      onQuiet()
    }
  }
  const silent = context.createGain()
  silent.gain.value = 0 // keeps the graph running without playing the microphone back
  source.connect(tap)
  tap.connect(silent)
  silent.connect(context.destination)
  const close = async () => {
    tap.port.onmessage = null
    tap.disconnect()
    silent.disconnect()
    source.disconnect()
    for (const track of stream.getTracks()) track.stop()
    await context.close()
  }
  return {
    stop: async () => {
      await close()
      const samples = new Float32Array(chunks.reduce((n, c) => n + c.length, 0))
      let at = 0
      for (const c of chunks) {
        samples.set(c, at)
        at += c.length
      }
      return samples
    },
    cancel: () => {
      void close()
    },
  }
}

async function transcribeOnServer(samples: Float32Array): Promise<string> {
  const token = getToken()
  const response = await fetch(`${API_BASE}/voice/transcribe`, {
    method: 'POST',
    headers: {
      'Content-Type': 'audio/wav',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: encodeWav(samples),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new ApiError(response.status, body.detail ?? response.statusText)
  }
  return ((await response.json()) as { text: string }).text
}

async function transcribeOnDevice(samples: Float32Array): Promise<string> {
  return (await loadWhisper())(samples)
}

/** Start a listening turn. With `onQuiet`, the turn tells its caller when the person has
 * stopped talking (used after the wake word, where nobody taps to send). */
export async function listen(
  engine: SpeechEngine,
  onInterim: (text: string) => void,
  onQuiet?: () => void,
): Promise<Listening> {
  if (engine === 'browser') return listenInBrowser(onInterim, onQuiet)
  const recording = await record(onQuiet)
  const transcribe = engine === 'device' ? transcribeOnDevice : transcribeOnServer
  return {
    stop: async () => transcribe(await recording.stop()),
    cancel: recording.cancel,
  }
}
