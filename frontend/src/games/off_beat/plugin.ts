import { parse } from 'yaml'

import { shuffle, type Rng } from '../../lib/rng'
import { el, itemsToTimeline, makePlugin } from '../../taskhost/plugin'
import { practiceFeedback, wait } from '../../taskhost/respond'
import type { GameModule, TrialRecord } from '../../taskhost/types'
import { choose, scored } from '../shared/ask'
import rawConfig from './config.yaml?raw'

interface Config {
  trials: number
  beat_ms: number
  deadline_ms: number
}
const config = parse(rawConfig) as Config

export interface BeatItem {
  beats: number
  beat_ms: number
  /** How far the last beat moves, in ms: 0 on the beat, negative early, positive late. */
  shift_ms: number
  deadline_ms: number
}

/** Half the steps end on the beat, half off it (early or late by `shiftPct` of the beat). */
export function makeItems(rng: Rng, count: number, beats: number, shiftPct: number): BeatItem[] {
  const off = Array.from({ length: count }, (_, i) => i % 2 === 1)
  const shift = Math.round((config.beat_ms * shiftPct) / 100)
  return shuffle(rng, off).map((isOff) => ({
    beats: Math.max(3, Math.round(beats)),
    beat_ms: config.beat_ms,
    shift_ms: isOff ? (rng() < 0.5 ? -shift : shift) : 0,
    deadline_ms: config.deadline_ms,
  }))
}

/** When each beat comes, in ms from the first one. */
export function onsets(item: BeatItem): number[] {
  return Array.from(
    { length: item.beats },
    (_, i) => i * item.beat_ms + (i === item.beats - 1 ? item.shift_ms : 0),
  )
}

/** Blink the dot and tick on every beat. The ticks are scheduled on the audio clock, which is
 * more precise than timers; the blink times actually reached are returned for re-scoring. */
async function playBeats(stage: HTMLElement, item: BeatItem): Promise<number[]> {
  const dot = el('div', 'ob-dot')
  dot.dataset['testid'] = 'beat-dot'
  stage.append(dot)
  const times = onsets(item)
  const lead = 150
  let audio: AudioContext | null = null
  try {
    audio = new AudioContext()
    for (const t of times) {
      const tick = audio.createOscillator()
      tick.frequency.value = 1000
      tick.connect(audio.destination)
      const at = audio.currentTime + (lead + t) / 1000
      tick.start(at)
      tick.stop(at + 0.04)
    }
  } catch {
    // No sound available: the blink alone carries the beat.
  }
  const start = performance.now() + lead
  const seen: number[] = []
  for (const t of times) {
    await wait(Math.max(0, start + t - performance.now()))
    seen.push(Math.round(performance.now() - start))
    dot.classList.add('is-on')
    window.setTimeout(() => {
      dot.classList.remove('is-on')
    }, 90)
  }
  await wait(300)
  void audio?.close()
  return seen
}

const OffBeatPlugin = makePlugin<BeatItem>(
  'najma-off-beat',
  async ({ jsPsych, stage, item, practice, e2e }) => {
    const seen = await playBeats(stage, item)
    const off = item.shift_ms !== 0
    const { index, rt } = await choose(
      jsPsych,
      stage,
      e2e,
      ['On the beat', 'Off the beat'],
      off ? 1 : 0,
      { keys: ['f', 'j'], deadlineMs: item.deadline_ms },
    )
    const correct = index === (off ? 1 : 0)
    if (practice) await practiceFeedback(stage, correct)
    else await wait(250)
    return {
      stimulus: { ...item, onsets_ms: seen },
      response: index === null ? null : { off: index === 1 },
      correct,
      rt_ms: rt,
    }
  },
)

/** Accuracy, and how often an off beat was noticed (hits) or a steady one called off. */
export function metrics(trials: TrialRecord[]): Record<string, number> {
  const s = scored(trials)
  const rate = (steps: TrialRecord[]) =>
    steps.length ? steps.filter((t) => t.response?.['off'] === true).length / steps.length : 0
  return {
    accuracy: s.length ? s.filter((t) => t.correct === true).length / s.length : 0,
    hit_rate: rate(s.filter((t) => t.stimulus['shift_ms'] !== 0)),
    false_alarm_rate: rate(s.filter((t) => t.stimulus['shift_ms'] === 0)),
  }
}

export const game: GameModule = {
  id: 'off_beat',
  name: 'Off Beat',
  instructions:
    'A dot blinks and ticks to a steady beat. Watch and listen: did the last beat come on the beat, or a little early or late?',
  keysHint: 'F for on the beat, J for off the beat, or tap the buttons.',
  timeline({ spec, rng, e2e }) {
    const items = makeItems(
      rng,
      spec.practice_trials + config.trials,
      spec.knobs['beats'] ?? 5,
      spec.knobs['shift_pct'] ?? 18,
    )
    return itemsToTimeline(OffBeatPlugin, items, spec.practice_trials, e2e)
  },
  metrics,
}
