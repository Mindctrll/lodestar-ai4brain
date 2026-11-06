"""What the agent asks the browser to play, and what comes back (docs/plan/02, 03, 08)."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue

from backend.contracts.affect import BehaviourSignals
from backend.contracts.common import Contract, GameId, Level, PlayMode, Probability


class WhyLine(Contract):
    """One piece of evidence behind a pick, and the chart or card it comes from."""

    source: str = Field(description="Progress curve, Time-of-day heatmap, Response time, ...")
    text: str


class ExerciseSpec(Contract):
    """Payload of the `play` interrupt."""

    round_id: UUID
    game_id: GameId
    mode: PlayMode
    target_p: Probability = Field(description="Success rate the level aims for")
    level: Level
    difficulty_b: float = Field(description="Item difficulty on the logit scale")
    knobs: dict[str, float]
    content: dict[str, JsonValue] | None = Field(
        default=None, description="Generated items for games that need them"
    )
    content_item_id: UUID | None = None
    theme: str | None = None
    seed: int
    practice_trials: int = Field(ge=0)
    duration_s: int = Field(ge=0)
    reason: str = Field(min_length=1, description="Why this exercise, in plain words")
    why: list[WhyLine] = Field(default_factory=list, description="The data behind the reason")
    track: Literal["advanced", "foundation", "new_format"] | None = Field(
        default=None, description="Set when a split profile or a plateau shaped this pick"
    )


RoundStatus = Literal["completed", "stopped", "eased"]
StopReason = Literal["user", "frustration", "error"]


class RoundResult(Contract):
    """Resume value after a game. Trials themselves arrive through POST /events."""

    round_id: UUID
    game_id: GameId
    status: RoundStatus
    stop_reason: StopReason | None = None
    trial_count: int = Field(ge=0)
    metrics: dict[str, float] = Field(default_factory=dict)
    final_level: Level
    started_at: AwareDatetime
    ended_at: AwareDatetime
    behaviour: BehaviourSignals | None = Field(
        default=None, description="Play signals summarised by the browser (docs/plan/12)"
    )
