import paramsUrl from './porcupine_params.pv?url'

/** "Hey Najma" (docs/plan/12, Summon): Porcupine Web listens on this device for the keyword
 * only and keeps nothing. It needs the person's own Picovoice AccessKey and their "Hey Najma"
 * keyword file (.ppn for Web, made in the Picovoice Console). Both stay in this browser; they
 * are never sent to Najma's server (AGENTS.md rule 9). Without them the wake word is off and
 * tap-to-talk works as always. */
export interface WakeSetup {
  accessKey: string
  /** The .ppn keyword file, base64. */
  keyword: string
}

const WAKE_KEY = 'najma.voice.wake'
export const WAKE_LABEL = 'Hey Najma'
const SENSITIVITY = 0.5

export function wakeSetup(): WakeSetup | null {
  try {
    const saved = JSON.parse(localStorage.getItem(WAKE_KEY) ?? 'null') as WakeSetup | null
    return saved?.accessKey && saved.keyword ? saved : null
  } catch {
    return null
  }
}

export function saveWakeSetup(setup: WakeSetup | null): void {
  try {
    if (setup) localStorage.setItem(WAKE_KEY, JSON.stringify(setup))
    else localStorage.removeItem(WAKE_KEY)
  } catch {
    // no storage: the wake word stays off
  }
}

/** What the screen may show of the key: its last four characters. */
export function maskedKey(key: string): string {
  return `••••${key.slice(-4)}`
}

/** Start listening for "Hey Najma". Resolves with a function that stops it. */
export async function startWake(setup: WakeSetup, onWake: () => void): Promise<() => void> {
  const [{ PorcupineWorker }, { WebVoiceProcessor }] = await Promise.all([
    import('@picovoice/porcupine-web'),
    import('@picovoice/web-voice-processor'),
  ])
  const worker = await PorcupineWorker.create(
    setup.accessKey,
    [{ base64: setup.keyword, label: WAKE_LABEL, sensitivity: SENSITIVITY }],
    onWake,
    { publicPath: paramsUrl },
  )
  await WebVoiceProcessor.subscribe(worker)
  return () => {
    void WebVoiceProcessor.unsubscribe(worker).then(async () => {
      await worker.release()
      worker.terminate()
    })
  }
}
