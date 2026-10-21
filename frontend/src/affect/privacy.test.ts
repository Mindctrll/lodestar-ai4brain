import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { startCamera, strainFromBlendshapes, type FaceDetector } from './camera'
import { activeSignals, sendCues } from './cues'

/** Network test (WP3.5, docs/plan/12 rule 2): while the camera runs, nothing at all leaves the
 * browser; afterwards the only request is the coarse cue, one number with one decimal. Every way
 * out of the page is watched: fetch, XMLHttpRequest, WebSocket and sendBeacon. */

const SESSION = '00000000-0000-4000-8000-000000000001'
const fetchSpy = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
  Promise.resolve(new Response(null, { status: 204 })),
)
const xhrSpy = vi.fn()
const wsSpy = vi.fn()
const beaconSpy = vi.fn(() => true)

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', fetchSpy)
  vi.stubGlobal('WebSocket', wsSpy)
  vi.spyOn(XMLHttpRequest.prototype, 'send').mockImplementation(xhrSpy)
  Object.defineProperty(navigator, 'sendBeacon', { value: beaconSpy, configurable: true })
  const track = { stop: vi.fn() }
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn(() => Promise.resolve({ getTracks: () => [track] })),
    },
  })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  Object.defineProperty(HTMLMediaElement.prototype, 'readyState', {
    configurable: true,
    get: () => 4,
  })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  fetchSpy.mockClear()
})

const close = vi.fn()

function tenseFace(): FaceDetector {
  const scores = {
    browDownLeft: 0.5,
    browDownRight: 0.5,
    mouthPressLeft: 0.5,
    mouthPressRight: 0.5,
  }
  return {
    detectForVideo: () => ({
      faceBlendshapes: [
        {
          categories: Object.entries(scores).map(([categoryName, score]) => ({
            categoryName,
            score,
          })),
        },
      ],
    }),
    close,
  }
}

function requests(): { url: string; body: unknown }[] {
  return fetchSpy.mock.calls.map(([url, init]) => ({
    url,
    body: JSON.parse(init?.body as string) as unknown,
  }))
}

describe('camera strain cues', () => {
  it('reads brow furrow and mouth press as strain, a relaxed face as none', () => {
    expect(strainFromBlendshapes({})).toBe(0)
    const tense = strainFromBlendshapes({
      browDownLeft: 0.6,
      browDownRight: 0.6,
      mouthPressLeft: 0.6,
      mouthPressRight: 0.6,
    })
    expect(tense).toBeCloseTo(0.6)
  })

  it('sends no frames, only one coarse number', async () => {
    const stop = await startCamera(tenseFace())
    expect(activeSignals()).toEqual(['camera']) // the on-screen indicator reads this
    await vi.advanceTimersByTimeAsync(25_000)
    expect(fetchSpy).not.toHaveBeenCalled()
    stop()
    expect(activeSignals()).toEqual([])
    expect(close).toHaveBeenCalled()

    await sendCues(SESSION)
    const sent = requests()
    expect(sent).toHaveLength(1)
    expect(sent[0]?.url).toBe('/api/affect/cues')
    expect(sent[0]?.body).toEqual({ session_id: SESSION, strain_cue: 0.6, voice_strain_cue: null })
    expect(xhrSpy).not.toHaveBeenCalled()
    expect(wsSpy).not.toHaveBeenCalled()
    expect(beaconSpy).not.toHaveBeenCalled()

    await sendCues(SESSION) // nothing new: nothing sent
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })
})
