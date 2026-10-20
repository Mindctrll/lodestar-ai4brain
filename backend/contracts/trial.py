"""One answer in one game (docs/plan/06, shared game rules)."""

from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue

from backend.contracts.common import Contract, GameId, Level, Milliseconds, Probability


class TrialEvent(Contract):
    trial_id: UUID
    round_id: UUID
    session_id: UUID
    game_id: GameId
    level: Level
    trial_index: int = Field(ge=0)
    practice: bool = False
    stimulus: dict[str, JsonValue]
    response: dict[str, JsonValue] | None = None
    correct: bool | None = Field(
        default=None, description="None for style and rubric games, which have no right answer"
    )
    rt_ms: Milliseconds | None = None
    hint_level: int = Field(default=0, ge=0)
    confidence: Probability | None = Field(
        default=None, description="Answer to 'How sure are you?' when asked"
    )
    ts: AwareDatetime
