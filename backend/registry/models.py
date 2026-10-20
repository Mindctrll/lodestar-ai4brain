"""Typed registry entries (docs/plan/05, 06, 03). The YAML files in `registry/` are validated
against these models; `make contracts` exports their JSON Schemas for editors."""

import math
from typing import Literal

from pydantic import Field, HttpUrl, model_validator

from backend.contracts.common import Contract, DimensionId, GameId, PlayMode, ProviderId

Badge = Literal["established", "moderate", "experimental"]
SkyGroup = Literal["attention", "control", "memory", "speed", "reasoning", "language", "style"]
Phase = Literal["P1", "P2", "L"]
Origin = Literal["classic", "original", "custom"]
Scoring = Literal["binary", "hshs", "span", "continuous", "rubric", "style", "calibration", "none"]
ContentSource = Literal["code", "llm", "code_with_llm_hints"]
Modality = Literal["keyboard", "touch", "voice"]
AcsHook = Literal["verification", "autonomy", "iteration", "clarification", "responsible_use"]

# docs/plan/07: how much each kind of game is trusted.
DEFAULT_RELIABILITY: dict[Origin, float] = {"classic": 1.0, "original": 0.8, "custom": 0.4}


class Dimension(Contract):
    id: DimensionId
    name: str
    plain: str
    badge: Badge
    in_overall: bool
    group: SkyGroup
    framework: list[str]
    main_metric: str
    biases: list[str]
    note: str | None = None
    style: bool = Field(default=False, description="Shown as a style, not better or worse")
    sources: list[HttpUrl]

    @model_validator(mode="after")
    def _experimental_not_in_overall(self) -> Dimension:
        if self.badge == "experimental" and self.in_overall:
            raise ValueError(f"{self.id}: experimental dimensions are excluded from overall scores")
        return self


class Knob(Contract):
    """A difficulty knob: its value at level 0 (easy) and level 1 (hard)."""

    easy: float
    hard: float
    unit: str | None = None

    @property
    def is_int(self) -> bool:
        return float(self.easy).is_integer() and float(self.hard).is_integer()

    def at(self, level: float) -> float:
        # This form is exact at both ends (level 0 gives `easy`, level 1 gives `hard`).
        value = self.easy * (1.0 - level) + self.hard * level
        # Half-up rounding, matching JavaScript's Math.round in the browser.
        return float(math.floor(value + 0.5)) if self.is_int else value


class Game(Contract):
    id: GameId
    name: str
    kind: Literal["game", "story", "probe"]
    phase: Phase
    dims: dict[DimensionId, float]
    origin: Origin
    reliability: float | None = Field(default=None, gt=0.0, le=1.0)
    paradigm: str
    code_source: str
    does: str
    scoring: Scoring
    duration_s: int = Field(ge=0)
    metrics: list[str]
    knobs: dict[str, Knob]
    staircase: str | None = Field(default=None, description="Knob tuned inside the game")
    level_map: Literal["linear", "none"]
    content: ContentSource
    modalities: list[Modality]
    acs_hooks: list[AcsHook]
    practice_trials: int = Field(ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> Game:
        for dim, loading in self.dims.items():
            if not 0.0 < loading <= 1.0:
                raise ValueError(f"{self.id}: loading on {dim} must be in (0, 1]")
        if self.kind == "game" and (not self.dims or max(self.dims.values()) != 1.0):
            raise ValueError(f"{self.id}: a game needs one primary dimension (loading 1.0)")
        if (self.level_map == "linear") != bool(self.knobs):
            raise ValueError(f"{self.id}: level_map 'linear' needs knobs, 'none' needs none")
        return self

    @property
    def effective_reliability(self) -> float:
        return (
            self.reliability if self.reliability is not None else DEFAULT_RELIABILITY[self.origin]
        )

    @property
    def primary_dims(self) -> list[str]:
        return [d for d, w in self.dims.items() if w == 1.0]

    def knobs_at(self, level: float) -> dict[str, float]:
        return {name: knob.at(level) for name, knob in self.knobs.items()}


class ProviderCapabilities(Contract):
    structured_output: bool = True
    tool_calling: bool = True
    streaming: bool = True
    forced_tool_choice: bool = True
    sampling_params: bool = True


class LlmProvider(Contract):
    id: ProviderId
    name: str
    integration: str
    api_base: HttpUrl | None = Field(
        default=None, description="Provider API root; Ollama's comes from OLLAMA_URL"
    )
    hosting: str
    console_url: HttpUrl | None = None
    needs_key: bool
    default_model: str
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)
    notes: str | None = None
    hidden: bool = False


class Battery(Contract):
    seconds_each: int = Field(gt=0)
    mode: PlayMode
    games: list[GameId] = Field(min_length=1)


class Registry(Contract):
    dimensions: list[Dimension]
    games: list[Game]
    providers: list[LlmProvider]
    batteries: dict[str, Battery]

    @model_validator(mode="after")
    def _cross_references(self) -> Registry:
        dim_ids = [d.id for d in self.dimensions]
        game_ids = [g.id for g in self.games]
        for label, ids in (("dimension", dim_ids), ("game", game_ids)):
            dupes = {i for i in ids if ids.count(i) > 1}
            if dupes:
                raise ValueError(f"duplicate {label} ids: {sorted(dupes)}")
        known = set(dim_ids)
        for game in self.games:
            unknown = set(game.dims) - known
            if unknown:
                raise ValueError(f"{game.id}: unknown dimensions {sorted(unknown)}")
        measured = {d for g in self.games for d in g.dims}
        unmeasured = known - measured
        if unmeasured:
            raise ValueError(f"dimensions with no game: {sorted(unmeasured)}")
        for name, battery in self.batteries.items():
            missing = set(battery.games) - set(game_ids)
            if missing:
                raise ValueError(f"battery {name}: unknown games {sorted(missing)}")
        return self

    def dimension(self, dim_id: str) -> Dimension:
        return next(d for d in self.dimensions if d.id == dim_id)

    def game(self, game_id: str) -> Game:
        return next(g for g in self.games if g.id == game_id)

    def provider(self, provider_id: str) -> LlmProvider:
        return next(p for p in self.providers if p.id == provider_id)

    def loadings(self) -> dict[str, dict[str, float]]:
        """game id -> {dimension id -> loading}."""
        return {g.id: dict(g.dims) for g in self.games}

    def core_skills(self) -> set[str]:
        """Dimensions the onboarding battery measures with a primary loading (docs/plan/07)."""
        battery = self.batteries["onboarding"]
        return {d for gid in battery.games for d in self.game(gid).primary_dims}
