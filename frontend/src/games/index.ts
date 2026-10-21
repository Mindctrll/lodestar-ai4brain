import type { GameModule } from '../taskhost/types'
import { game as arrowStorm } from './arrow_storm/plugin'
import { game as balloonPump } from './balloon_pump/plugin'
import { game as brake } from './brake/plugin'
import { game as callback } from './callback/plugin'
import { game as cardGamble } from './card_gamble/plugin'
import { game as connect } from './connect/plugin'
import { game as controlTower } from './control_tower/plugin'
import { game as digitsBack } from './digits_back/plugin'
import { game as customBlocks } from './custom_blocks/plugin'
import { game as echo } from './echo/plugin'
import { game as foldAndPunch } from './fold_and_punch/plugin'
import { game as guideTheRobot } from './guide_the_robot/plugin'
import { game as holdIt } from './hold_it/plugin'
import { game as inkClash } from './ink_clash/plugin'
import { game as lightPath } from './light_path/plugin'
import { game as logicLock } from './logic_lock/plugin'
import { game as lookHere } from './look_here/plugin'
import { game as marketList } from './market_list/plugin'
import { game as mazeEscape } from './maze_escape/plugin'
import { game as nameTags } from './name_tags/plugin'
import { game as nightGuard } from './night_guard/plugin'
import { game as numberLine } from './number_line/plugin'
import { game as oddOneOut } from './odd_one_out/plugin'
import { game as patternGap } from './pattern_gap/plugin'
import { game as quickDraw } from './quick_draw/plugin'
import { game as quickMaths } from './quick_maths/plugin'
import { game as scramble } from './scramble/plugin'
import { game as secretRules } from './secret_rules/plugin'
import { game as seenIt } from './seen_it/plugin'
import { game as soukRush } from './souk_rush/plugin'
import { game as spotTheMistake } from './spot_the_mistake/plugin'
import { game as sumAndKeep } from './sum_and_keep/plugin'
import { game as switchGame } from './switch/plugin'
import { game as symbolCode } from './symbol_code/plugin'
import { game as teachMe } from './teach_me/plugin'
import { game as tower } from './tower/plugin'
import { game as turnIt } from './turn_it/plugin'
import { game as twins } from './twins/plugin'
import { game as twoScreens } from './two_screens/plugin'
import { game as unusualUses } from './unusual_uses/plugin'
import { game as whichJar } from './which_jar/plugin'
import { game as wordBurst } from './word_burst/plugin'
import { game as zigzag } from './zigzag/plugin'

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
    // P2 (WP3.1)
    brake,
    lookHere,
    nightGuard,
    controlTower,
    digitsBack,
    seenIt,
    callback,
    twins,
    connect,
    zigzag,
    secretRules,
    tower,
    guideTheRobot,
    logicLock,
    wordBurst,
    scramble,
    teachMe,
    whichJar,
    quickMaths,
    balloonPump,
    // Built from blocks (WP3.7)
    customBlocks,
    // Late games (WP3.10)
    twoScreens,
    sumAndKeep,
    nameTags,
    mazeEscape,
    foldAndPunch,
    cardGamble,
    unusualUses,
  ].map((g) => [g.id, g]),
)
