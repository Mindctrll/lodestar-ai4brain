import type { GameModule } from '../taskhost/types'
import { game as echo } from './echo/plugin'
import { game as inkClash } from './ink_clash/plugin'
import { game as quickDraw } from './quick_draw/plugin'

/** Games the browser can run. A game is offered by the agent only when its registry entry says
 * `available: true`, and that must match this list (checked in tests). */
export const GAMES: Record<string, GameModule> = {
  [quickDraw.id]: quickDraw,
  [inkClash.id]: inkClash,
  [echo.id]: echo,
}
