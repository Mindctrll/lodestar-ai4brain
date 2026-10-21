import { encodeWav } from './speech'
import { forSpeech } from './tts'

test('recordings are sent as 16 kHz mono 16-bit WAV', () => {
  const samples = new Float32Array([0, 0.5, -0.5, 1, -1, 2])
  const view = new DataView(encodeWav(samples))
  const text = (at: number, n: number) =>
    String.fromCharCode(...Array.from({ length: n }, (_, i) => view.getUint8(at + i)))
  expect(text(0, 4)).toBe('RIFF')
  expect(text(8, 4)).toBe('WAVE')
  expect(view.getUint16(22, true)).toBe(1) // mono
  expect(view.getUint32(24, true)).toBe(16000)
  expect(view.getUint16(34, true)).toBe(16) // bits per sample
  expect(view.getUint32(40, true)).toBe(samples.length * 2)
  expect(view.getInt16(44 + 2, true)).toBe(16383) // 0.5
  expect(view.getInt16(44 + 10, true)).toBe(32767) // 2 is clipped to 1
})

test('citations are for the screen, not for the ear', () => {
  expect(forSpeech('Speed estimate 54% (80% range 41-66%) [F1]. Why this game [D1, F2]?')).toBe(
    'Speed estimate 54% (80% range 41-66%). Why this game?',
  )
  expect(forSpeech('Within ±20 points [F1].')).toBe('Within plus or minus 20 points.')
})
