import type { GameModule } from '../taskhost/types'
import { game as arrowStorm } from './arrow_storm/plugin'
import { game as echo } from './echo/plugin'
import { game as holdIt } from './hold_it/plugin'
import { game as inkClash } from './ink_clash/plugin'
import { game as lightPath } from './light_path/plugin'
import { game as marketList } from './market_list/plugin'
import { game as numberLine } from './number_line/plugin'
import { game as oddOneOut } from './odd_one_out/plugin'
import { game as patternGap } from './pattern_gap/plugin'
import { game as quickDraw } from './quick_draw/plugin'
import { game as soukRush } from './souk_rush/plugin'
import { game as spotTheMistake } from './spot_the_mistake/plugin'
import { game as switchGame } from './switch/plugin'
import { game as symbolCode } from './symbol_code/plugin'
import { game as turnIt } from './turn_it/plugin'

/** Games the browser can run. A game is offered by the agent only when its registry entry says
 * `available: true`, and that must match this list (checked in tests). */
export const GAMES: Record<string, GameModule> = Object.fromEntries(
  [
    quickDraw,
    inkClash,
    echo,
    arrowStorm,
    oddOneOut,
    holdIt,
    lightPath,
    marketList,
    soukRush,
    symbolCode,
    switchGame,
    patternGap,
    spotTheMistake,
    turnIt,
    numberLine,
  ].map((g) => [g.id, g]),
)
