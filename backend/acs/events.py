"""Turn play into ACS observations (docs/plan/11, "Components and how we measure them").

V  critical verification: every Spot the AI's Mistake item (flag a wrong solution or accept a
   right one; balanced, so blanket distrust doesn't win).
A  autonomy: every Pattern Gap item, where hints are available: a success is solving it without
   asking for a hint first.
I  iteration: a game played again after a failed round; a success is a better score. Also every
   Guide the Robot item whose first try failed: a success is a changed retry that works.
R  responsible use: a suggested break; a success is not starting a new session within 10 minutes.
C  clarification: every Guide the Robot and Teach Me item; a success is asking Lodestar first when
   the request is ambiguous and not asking when it is clear.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from backend.contracts.acs import AcsComponent
from backend.contracts.trial import TrialEvent

FAILED_ROUND = 0.5
BREAK_MINUTES = 10
CLARIFY_GAMES = ("guide_the_robot", "teach_me")


@dataclass(frozen=True)
class Observation:
    component: AcsComponent
    success: bool
    source: str


def from_trials(game_id: str, trials: Sequence[TrialEvent]) -> list[Observation]:
    out: list[Observation] = []
    for t in trials:
        if t.practice:
            continue
        if game_id in CLARIFY_GAMES:
            if t.response is None:
                continue
            asked = bool(t.response.get("asked_first"))
            out.append(Observation("C", asked == bool(t.stimulus.get("ambiguous")), game_id))
            if game_id == "guide_the_robot" and t.response.get("first_failed"):
                out.append(Observation("I", bool(t.response.get("solved")), game_id))
        elif t.correct is None:
            continue
        elif game_id == "spot_the_mistake":
            out.append(Observation("V", t.correct, game_id))
        elif game_id == "pattern_gap":
            out.append(Observation("A", t.correct and t.hint_level == 0, game_id))
    return out


def iteration(game_id: str, previous_score: float | None, score: float | None) -> list[Observation]:
    """A retry after a failed round of the same game."""
    if previous_score is None or score is None or previous_score >= FAILED_ROUND:
        return []
    return [Observation("I", score > previous_score, game_id)]
