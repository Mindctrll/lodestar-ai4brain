"""Session-level routing and planning (docs/plan/03)."""

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from backend.contracts.common import (
    Contract,
    DimensionId,
    GameId,
    PlayMode,
    Probability,
    SuccessMode,
)
from backend.contracts.events import DimensionChange
from backend.contracts.facts import FactsPacket

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
    avoid_dims: list[DimensionId] = Field(
        default_factory=list, description="Skills the user turned down for today (UW3)"
    )
    quick: bool = Field(default=False, description="The user asked for something short")
    replace_current: bool = Field(
        default=False, description="'Not that one': anything but the game just suggested"
    )
    tool: str | None = Field(default=None, description="The converse tool, when already known")
    source: Literal["rules", "llm"] = "rules"


ToolName = Literal[
    "read_profile",
    "get_history",
    "search_memory",
    "start_game",
    "set_goal",
    "log_life_context",
    "explain",
    "update_settings",
    "start_experiment",
]


class ToolCall(Contract):
    """A converse tool Najma is about to use (docs/plan/03, converse subgraph). Tools that write
    carry the question shown before writing, and the facts behind any number in it."""

    call_id: UUID
    name: ToolName
    args: dict[str, JsonValue] = Field(default_factory=dict)
    writes: bool = False
    prompt: str | None = None
    facts: FactsPacket = Field(default_factory=FactsPacket)


class ToolOutcome(Contract):
    """What a tool found or did. `reply` is fixed text; without it the coach drafts a verified
    answer from `facts` following `instruction`."""

    name: ToolName | None = None
    facts: FactsPacket = Field(default_factory=FactsPacket)
    reply: str | None = None
    instruction: str | None = None
    fallback: str | None = Field(
        default=None, description="Fixed text from the facts, used when no draft passes"
    )


class SessionBudget(Contract):
    max_rounds: int = Field(default=3, ge=1)
    max_minutes: float = Field(default=15.0, gt=0)
    fatigue_point_min: float | None = Field(
        default=None, gt=0, description="Minutes after which this user's speed usually drops"
    )


class SessionPlan(Contract):
    game_id: GameId | None = Field(default=None, description="The game plan_next picked")
    mode: PlayMode
    success_mode: SuccessMode
    target_p: Probability
    declined_dims: list[DimensionId] = Field(
        default_factory=list, description="Skills the user declined today"
    )
    goal_weights: dict[DimensionId, float] = Field(default_factory=dict)


Verdict = Literal["continue", "ease", "break", "end"]


class RoundSummary(Contract):
    """What `score_update` hands to `monitor` and `reflect` about the round just played."""

    round_id: str
    game_id: GameId
    status: Literal["completed", "stopped", "eased"]
    mean_score: float | None
    accuracy: float | None
    correct: int = 0
    answered: int = 0
    observations: int
    changes: list[DimensionChange] = Field(default_factory=list)
    quality_verdict: str = "ok"
