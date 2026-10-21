import { useEffect, useRef } from 'react'

import type { Persona } from '../api/types'
import type { SessionState } from '../app/useSession'
import { speak } from './tts'

/** Speak Najma's new lines (chat replies and the after-game coach) in the coach's voice. The
 * same lines are always on screen. */
export function useSpeakReplies(state: SessionState, persona: Persona, enabled: boolean): void {
  const spoken = useRef({ chat: 0, says: 0 })
  useEffect(() => {
    const najma = state.chat.filter((l) => l.who === 'najma')
    // Both lists start again (a new session, a new round): count from the start then.
    const chatFrom = najma.length < spoken.current.chat ? 0 : spoken.current.chat
    const saysFrom = state.says.length < spoken.current.says ? 0 : spoken.current.says
    const fresh = [
      ...najma.slice(chatFrom).map((l) => l.text),
      ...state.says.slice(saysFrom).map((l) => l.text),
    ]
    spoken.current = { chat: najma.length, says: state.says.length }
    if (enabled) for (const line of fresh) speak(line, persona)
  }, [state.chat, state.says, persona, enabled])
}
