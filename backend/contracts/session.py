"""Session-level routing and planning (docs/plan/03)."""

from typing import Literal

from pydantic import Field

from backend.contracts.common import (
    Contract,
    DimensionId,
    GameId,
    PlayMode,
    Probability,
    SuccessMode,
)

IntentKind = Literal[
    "play",
    "proactive",
    "chat",
    "twin_chat",
    "experiment",
    "goal",
    "life_context",
    "settings",
    "refuse",
]


class Intent(Contract):
    kind: IntentKind
    game_id: GameId | None = None
    dim: DimensionId | None = None
    theme: str | None = Field(default=None, max_length=40)
    text: str | None = None


class SessionBudget(Contract):
    max_rounds: int = Field(default=3, ge=1)
    max_minutes: float = Field(default=15.0, gt=0)
    fatigue_point_min: float | None = Field(
        default=None, gt=0, description="Minutes after which this user's speed usually drops"
    )


class SessionPlan(Contract):
    mode: PlayMode
    success_mode: SuccessMode
    target_p: Probability
    declined_dims: list[DimensionId] = Field(
        default_factory=list, description="Skills the user declined today"
    )
    goal_weights: dict[DimensionId, float] = Field(default_factory=dict)
