import { initJsPsych, type JsPsych } from 'jspsych'
import { useEffect, useMemo, useRef } from 'react'

import { api } from '../api/client'
import type { ExerciseSpec, RoundResult, TrialEvent } from '../api/types'
import { mulberry32 } from '../lib/rng'
import { TrialBatcher } from './batcher'
import type { GameModule, TrialRecord } from './types'

export type FinishStatus = 'completed' | 'stopped' | 'eased'

interface Props {
  spec: ExerciseSpec
  sessionId: string
  game: GameModule
  onFinish: (result: RoundResult) => void
  onProgress?: (done: number, total: number) => void
  send?: (trials: TrialEvent[]) => Promise<unknown>
  /** Imperative controls for the game frame's buttons. */
  controlsRef?: React.RefObject<TaskControls | null>
}

export interface TaskControls {
  stop: (status: Exclude<FinishStatus, 'completed'>) => void
  pause: () => void
  resume: () => void
}

function toEvent(record: TrialRecord, spec: ExerciseSpec, sessionId: string): TrialEvent {
  return {
    trial_id: crypto.randomUUID(),
    round_id: spec.round_id,
    session_id: sessionId,
    game_id: spec.game_id,
    level: spec.level,
    trial_index: record.trial_index,
    practice: record.practice,
    stimulus: record.stimulus,
    response: record.response,
    correct: record.correct,
    rt_ms: record.rt_ms,
    hint_level: record.hint_level ?? 0,
    ts: new Date().toISOString(),
  }
}

/** Mounts a game's jsPsych timeline, streams every trial to the API and reports the round. */
export function TaskHost({
  spec,
  sessionId,
  game,
  onFinish,
  onProgress,
  send,
  controlsRef,
}: Props) {
  const stageRef = useRef<HTMLDivElement>(null)
  // Build the timeline from the spec's seed up front, so a bad spec shows an error, not a crash.
  const built = useMemo(() => {
    try {
      const rng = mulberry32(spec.seed)
      return {
        timeline: game.timeline({ spec, rng, e2e: window.__NAJMA_E2E__ === true }),
        error: null,
      }
    } catch (e) {
      return { timeline: [], error: e instanceof Error ? e.message : String(e) }
    }
  }, [spec, game])
  // Callbacks change identity on every parent render; keep the latest ones in a ref so the
  // timeline isn't torn down and restarted each time.
  const callbacks = useRef({ onFinish, onProgress, send })
  useEffect(() => {
    callbacks.current = { onFinish, onProgress, send }
  })

  useEffect(() => {
    const element = stageRef.current
    if (!element || built.error) return
    const started = new Date()
    const records: TrialRecord[] = []
    const batcher = new TrialBatcher(callbacks.current.send ?? api.sendTrials)
    let status: FinishStatus = 'completed'
    let finished = false
    let disposed = false
    let steps = 0

    const finish = async () => {
      if (finished) return
      finished = true
      await batcher.close()
      const scored = records.filter((r) => !r.practice)
      callbacks.current.onFinish({
        round_id: spec.round_id,
        game_id: spec.game_id,
        status,
        stop_reason: status === 'stopped' ? 'user' : null,
        trial_count: scored.length,
        metrics: game.metrics(records),
        final_level: spec.level,
        started_at: started.toISOString(),
        ended_at: new Date().toISOString(),
      })
    }

    const timeline = built.timeline
    const total = timeline.length
    const jsPsych = initJsPsych({
      display_element: element,
      on_data_update: (data: Record<string, unknown>) => {
        const found = data['najma'] as TrialRecord[] | undefined
        if (!found || disposed) return
        for (const record of found) {
          records.push(record)
          batcher.add(toEvent(record, spec, sessionId))
        }
        steps += 1
        callbacks.current.onProgress?.(steps, total)
      },
      on_finish: () => void finish(),
    })
    callbacks.current.onProgress?.(0, total)
    if (controlsRef) {
      controlsRef.current = {
        stop: (s) => {
          status = s
          jsPsych.abortExperiment()
          void finish()
        },
        pause: () => {
          jsPsych.pauseExperiment()
        },
        resume: () => {
          jsPsych.resumeExperiment()
        },
      }
    }
    void jsPsych.run(timeline as unknown as Parameters<JsPsych['run']>[0])

    return () => {
      // Leaving the page mid-game: stop the timeline without reporting a result. The graph stays
      // paused at `play`, so the round can be resumed later (UW6).
      finished = true
      disposed = true
      if (controlsRef) controlsRef.current = null
      // Stop listening: an aborted timeline must not answer keys meant for its successor.
      jsPsych.pluginAPI.cancelAllKeyboardResponses()
      jsPsych.pluginAPI.clearAllTimeouts()
      jsPsych.abortExperiment()
      void batcher.close()
      element.innerHTML = ''
    }
  }, [built, spec, sessionId, game, controlsRef])

  if (built.error) return <p role="alert">Something went wrong loading this game: {built.error}</p>
  return <div ref={stageRef} className="najma-taskhost" data-testid="taskhost" />
}
