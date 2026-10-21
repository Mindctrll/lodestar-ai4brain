import { useEffect } from 'react'

import { api } from '../api/client'
import { recordCue, signalStarted, signalStopped } from './cues'

/** Camera strain cues (docs/plan/12, "Optional camera"; WP3.5). MediaPipe Face Landmarker runs in
 * this browser on the camera's frames and gives 52 blendshape scores; a few of them (brow furrow,
 * eye squint, mouth press, eye closure) become one coarse `strain_cue` per 10 seconds. Frames are
 * never stored or sent: they go from the camera to a detached <video> element and the detector,
 * and nowhere else. These are expression features, not emotion labels. */

/** Loaded once, on first use. The wasm runtime is served with the app; the model file (about
 * 3.7 MB) comes from Google's model storage unless VITE_FACE_MODEL_URL points elsewhere. Both are
 * downloads into the browser; nothing goes the other way. */
export const FACE_MODEL_URL =
  (import.meta.env['VITE_FACE_MODEL_URL'] as string | undefined) ??
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'

const WINDOW_MS = 10_000
const SAMPLE_MS = 500
const MIN_SAMPLES = 4

/** Blendshape groups and how much each counts; `full` is the score that counts as fully on. */
const GROUPS: { names: string[]; weight: number; full: number }[] = [
  { names: ['browDownLeft', 'browDownRight'], weight: 0.35, full: 0.5 },
  { names: ['eyeSquintLeft', 'eyeSquintRight'], weight: 0.2, full: 0.6 },
  { names: ['mouthPressLeft', 'mouthPressRight'], weight: 0.25, full: 0.5 },
  { names: ['eyeBlinkLeft', 'eyeBlinkRight'], weight: 0.2, full: 0.8 },
]

export function strainFromBlendshapes(scores: Record<string, number>): number {
  let strain = 0
  for (const g of GROUPS) {
    const mean = g.names.reduce((sum, n) => sum + (scores[n] ?? 0), 0) / g.names.length
    strain += g.weight * Math.min(1, mean / g.full)
  }
  return Math.min(1, Math.max(0, strain))
}

/** The slice of MediaPipe's FaceLandmarker this module uses (and tests replace). */
export interface FaceDetector {
  detectForVideo(
    video: HTMLVideoElement,
    timestamp: number,
  ): { faceBlendshapes: { categories: { categoryName: string; score: number }[] }[] }
  close(): void
}

async function loadDetector(): Promise<FaceDetector> {
  const [vision, loader, binary] = await Promise.all([
    import('@mediapipe/tasks-vision'),
    import('@mediapipe/tasks-vision/vision_wasm_internal.js?url'),
    import('@mediapipe/tasks-vision/vision_wasm_internal.wasm?url'),
  ])
  return vision.FaceLandmarker.createFromOptions(
    { wasmLoaderPath: loader.default, wasmBinaryPath: binary.default },
    {
      baseOptions: { modelAssetPath: FACE_MODEL_URL },
      runningMode: 'VIDEO',
      numFaces: 1,
      outputFaceBlendshapes: true,
    },
  )
}

/** Start the camera and the cue loop; returns the stop function. */
export async function startCamera(detector?: FaceDetector): Promise<() => void> {
  const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240 } })
  let face: FaceDetector
  try {
    face = detector ?? (await loadDetector())
  } catch (e) {
    for (const track of stream.getTracks()) track.stop()
    throw e
  }
  const video = document.createElement('video') // never attached to the page
  video.muted = true
  video.playsInline = true
  video.srcObject = stream
  await video.play()

  let samples: number[] = []
  const sample = window.setInterval(() => {
    if (video.readyState < 2) return
    const [first] = face.detectForVideo(video, performance.now()).faceBlendshapes
    if (!first) return
    const scores: Record<string, number> = {}
    for (const c of first.categories) scores[c.categoryName] = c.score
    samples.push(strainFromBlendshapes(scores))
  }, SAMPLE_MS)
  const emit = window.setInterval(() => {
    if (samples.length >= MIN_SAMPLES)
      recordCue('camera', samples.reduce((a, b) => a + b, 0) / samples.length)
    samples = []
  }, WINDOW_MS)

  let stopped = false
  const stop = () => {
    if (stopped) return
    stopped = true
    window.clearInterval(sample)
    window.clearInterval(emit)
    for (const track of stream.getTracks()) track.stop()
    video.srcObject = null
    face.close()
    signalStopped('camera')
  }
  signalStarted('camera', stop)
  return stop
}

/** While `on` (a game is being played), run the camera if its switch is on. */
export function useCameraCues(on: boolean): void {
  useEffect(() => {
    if (!on) return
    let cancelled = false
    let stop: (() => void) | null = null
    const left = () => cancelled // read after an await
    api
      .consent()
      .then(async (view) => {
        if (left() || !view.switches.some((s) => s.id === 'camera' && s.granted)) return
        const started = await startCamera()
        if (left()) started()
        else stop = started
      })
      .catch(() => {
        // no camera, blocked, or the model didn't load: behaviour alone, as without the switch
      })
    return () => {
      cancelled = true
      stop?.()
    }
  }, [on])
}
