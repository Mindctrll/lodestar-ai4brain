import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

// Porcupine keeps its model files in IndexedDB; Node has none.
import 'fake-indexeddb/auto'
import { Porcupine } from '@picovoice/porcupine-web'

import { mulberry32 } from '../lib/rng'

/** Wake-word false triggers (WP3.4 done-when; docs/plan/12). Runs the real Porcupine engine over
 * background audio that never says "Hey Lodestar" and counts detections. Needs the person's own
 * key and keyword file, so it skips without them:
 *   PORCUPINE_ACCESS_KEY=...  PORCUPINE_KEYWORD_PPN=path/to/hey-lodestar_en_wasm_v4_0_0.ppn
 *   WAKE_BACKGROUND_WAV=path/to/background.wav   (optional: the 30-minute run)
 * Without WAKE_BACKGROUND_WAV it uses about two minutes built from the speech fixtures and noise.
 * See tests/fixtures/voice/README.md for making the 30-minute file. */
const ACCESS_KEY = process.env['PORCUPINE_ACCESS_KEY']
const KEYWORD = process.env['PORCUPINE_KEYWORD_PPN']
const FIXTURES = join(__dirname, '../../../tests/fixtures/voice')
const RATE = 16_000
// Picovoice aims for under one false alarm per 10 hours; we allow one per 30 minutes.
const ALLOWED_PER_30_MIN = 1

/** The samples of a 16 kHz mono 16-bit WAV file. */
function pcm(path: string): Int16Array {
  const file = readFileSync(path)
  let at = 12
  while (at < file.length) {
    const id = file.toString('ascii', at, at + 4)
    const size = file.readUInt32LE(at + 4)
    if (id === 'fmt ' && (file.readUInt16LE(at + 10) !== 1 || file.readUInt32LE(at + 12) !== RATE))
      throw new Error(`${path}: expected 16 kHz mono WAV`)
    if (id === 'data')
      return new Int16Array(
        file.buffer.slice(file.byteOffset + at + 8, file.byteOffset + at + 8 + size),
      )
    at += 8 + size + (size % 2)
  }
  throw new Error(`${path}: no audio`)
}

/** About two minutes: the speech fixtures, between stretches of quiet room noise. */
function builtInBackground(): Int16Array {
  const speech = readdirSync(FIXTURES)
    .filter((f) => f.endsWith('.wav'))
    .map((f) => pcm(join(FIXTURES, f)))
  const rng = mulberry32(34)
  const parts: Int16Array[] = []
  for (let round = 0; round < 12; round++)
    for (const clip of speech) {
      parts.push(
        clip,
        Int16Array.from({ length: RATE * 3 }, () => (rng() - 0.5) * 600),
      )
    }
  const out = new Int16Array(parts.reduce((n, p) => n + p.length, 0))
  let at = 0
  for (const p of parts) {
    out.set(p, at)
    at += p.length
  }
  return out
}

test.skipIf(!ACCESS_KEY || !KEYWORD)(
  'the wake word does not fire on background audio',
  async () => {
    const background = process.env['WAKE_BACKGROUND_WAV']
    const audio = background ? pcm(background) : builtInBackground()
    let triggers = 0
    const porcupine = await Porcupine.create(
      ACCESS_KEY ?? '',
      [
        {
          base64: readFileSync(KEYWORD ?? '').toString('base64'),
          label: 'Hey Lodestar',
          forceWrite: true,
        },
      ],
      () => {
        triggers += 1
      },
      {
        base64: readFileSync(join(__dirname, 'porcupine_params.pv')).toString('base64'),
        forceWrite: true,
      },
    )
    const frame = porcupine.frameLength
    for (let at = 0; at + frame <= audio.length; at += frame)
      await porcupine.process(audio.slice(at, at + frame))
    await porcupine.release()
    const minutes = audio.length / RATE / 60
    console.log(`wake word: ${String(triggers)} triggers in ${minutes.toFixed(1)} minutes`)
    expect(triggers).toBeLessThanOrEqual(Math.floor((minutes / 30) * ALLOWED_PER_30_MIN))
  },
  30 * 60_000,
)
