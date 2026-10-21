import type { JsPsych } from 'jspsych'

export interface ResponseTarget {
  element: HTMLElement
  key: string
}

export interface Response {
  key: string | null
  rt: number | null
}

/** Wait for a key press or a tap, whichever comes first, with an optional deadline.
 * Timing uses performance.now() from the moment the stimulus was painted. */
export function waitForResponse(
  jsPsych: JsPsych,
  options: {
    keys: string[]
    targets?: ResponseTarget[]
    deadlineMs: number | null
    /** Called once responses are being listened for (after the stimulus is painted). */
    onReady?: () => void
  },
): Promise<Response> {
  return new Promise((resolve) => {
    let done = false
    let start = performance.now()
    const cleanups: (() => void)[] = []
    const finish = (key: string | null, rt: number | null) => {
      if (done) return
      done = true
      for (const cleanup of cleanups) cleanup()
      resolve({ key, rt })
    }
    requestAnimationFrame(() => {
      start = performance.now()
      const listener = jsPsych.pluginAPI.getKeyboardResponse({
        callback_function: (info: { key: string; rt: number }) => {
          finish(info.key.toLowerCase(), performance.now() - start)
        },
        valid_responses: options.keys,
        rt_method: 'performance',
        persist: false,
        allow_held_key: false,
      })
      cleanups.push(() => {
        jsPsych.pluginAPI.cancelKeyboardResponse(listener)
      })
      for (const target of options.targets ?? []) {
        const onTap = (event: PointerEvent) => {
          event.preventDefault()
          finish(target.key, performance.now() - start)
        }
        target.element.addEventListener('pointerdown', onTap)
        cleanups.push(() => {
          target.element.removeEventListener('pointerdown', onTap)
        })
      }
      options.onReady?.()
      if (options.deadlineMs !== null) {
        const timer = window.setTimeout(() => {
          finish(null, null)
        }, options.deadlineMs)
        cleanups.push(() => {
          window.clearTimeout(timer)
        })
      }
    })
  })
}

export function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

/** Brief right/wrong mark, only after practice trials. */
export async function practiceFeedback(stage: HTMLElement, correct: boolean): Promise<void> {
  const mark = document.createElement('div')
  mark.className = `najma-feedback ${correct ? 'is-right' : 'is-wrong'}`
  mark.textContent = correct ? 'Right' : 'Not quite'
  stage.appendChild(mark)
  await wait(450)
}
