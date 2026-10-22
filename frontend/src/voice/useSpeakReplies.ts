import { useEffect, useRef } from 'react'

import type { Persona } from '../api/types'
import { lodestarLines, type SessionState } from '../app/useSession'
import { setCoachVoice, speak } from './tts'

/** Speak Lodestar's new lines (chat replies and the after-game coach) in the coach's voice. The
 * same lines are always on screen. */
export function useSpeakReplies(state: SessionState, persona: Persona, enabled: boolean): void {
  const spoken = useRef(0)
  useEffect(() => {
    setCoachVoice(persona, enabled)
  }, [persona, enabled])
  useEffect(() => {
    const lines = lodestarLines(state.feed)
    // A new session starts the feed again: count from the start then.
    const from = lines.length < spoken.current ? 0 : spoken.current
    spoken.current = lines.length
    if (enabled) for (const line of lines.slice(from)) speak(line, persona)
  }, [state.feed, persona, enabled])
}
