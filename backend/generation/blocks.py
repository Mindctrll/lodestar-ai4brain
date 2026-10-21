"""Custom games from blocks (docs/plan/08): the recipe schema and its validator.

The LLM writes a recipe using only the blocks below; it never writes code. This module is the
source of truth for what a valid recipe is: the browser's block engine
(`frontend/src/games/custom_blocks/`) runs any recipe that passes `check_recipe` and the
language filter. Items (digits, letters, words, shapes) are drawn in the browser from the round's
seed, from pools whose sizes are `POOL` below.
"""

import json
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError

from backend.coach.language import find_banned
from backend.contracts.common import Contract, DimensionId

MAX_SECONDS = 180  # "max 3 minutes"
ItemKind = Literal["digits", "letters", "words", "shapes"]
# Must match the pools in frontend/src/games/custom_blocks/config.yaml (checked in vitest).
POOL: dict[str, int] = {"digits": 10, "letters": 20, "words": 40, "shapes": 8}
ItemText = Annotated[str, Field(min_length=1, max_length=20)]
SCORED = {"recall", "choice", "rule", "react"}


class ShowItems(Contract):
    """Flash items one at a time: `"digits:7"` (drawn in the browser) or an explicit list."""

    block: Literal["show_items"]
    items: (
        Annotated[str, Field(pattern=r"^(digits|letters|words|shapes):([2-9]|1[0-2])$")]
        | list[ItemText]
    ) = Field(description='"<digits|letters|words|shapes>:<2-12>" or 2-12 short items')
    ms_each: int = Field(ge=300, le=3000)


class Distractor(Contract):
    """A filler task between seeing and recalling (not scored)."""

    block: Literal["distractor"]
    task: Literal["arithmetic:easy", "arithmetic:hard", "tapping"]
    seconds: int = Field(ge=5, le=60)


class Recall(Contract):
    """Recall the items of the last `show_items`: tap them in order, in any order, or say for
    each probe whether it was shown."""

    block: Literal["recall"]
    kind: Literal["free", "ordered", "recognition"]


class Choice(Contract):
    block: Literal["choice"]
    question: str = Field(min_length=3, max_length=160)
    options: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        min_length=2, max_length=6
    )
    answer: str = Field(min_length=1, max_length=40)


class Timer(Contract):
    """A countdown (not scored)."""

    block: Literal["timer"]
    seconds: int = Field(ge=1, le=30)


class Rule(Contract):
    """Sort numbers 1-9 by a rule; with `switch_after`, the rule swaps every that many trials."""

    block: Literal["rule"]
    rule: Literal["odd_even", "high_low"]
    trials: int = Field(ge=4, le=30)
    switch_after: int | None = Field(default=None, ge=2, le=20)


class React(Contract):
    """Press as soon as the target shows, hold back for distractors."""

    block: Literal["react"]
    target: str = Field(min_length=1, max_length=12)
    distractors: list[Annotated[str, Field(min_length=1, max_length=12)]] = Field(
        default_factory=list, max_length=5
    )
    deadline_ms: int = Field(ge=300, le=3000)
    trials: int = Field(ge=4, le=30)


class Feedback(Contract):
    """Show how the round is going so far (not scored)."""

    block: Literal["feedback"]
    level: Literal["brief", "full"] = "brief"


Step = Annotated[
    ShowItems | Distractor | Recall | Choice | Timer | Rule | React | Feedback,
    Field(discriminator="block"),
]


class Recipe(Contract):
    """What an LLM writes for a custom game (docs/plan/08, "Recipe example")."""

    title: str = Field(min_length=3, max_length=40)
    dims: dict[DimensionId, float] = Field(
        min_length=1, max_length=3, description="Skills it trains; the main one has loading 1.0"
    )
    steps: list[Step] = Field(min_length=1, max_length=10)
    repeat: int = Field(default=1, ge=1, le=5)


class CustomGameContent(Recipe):
    """The served content: the recipe plus the user's request it was written for."""

    asked: str | None = Field(default=None, max_length=300)


def _shown(step: ShowItems) -> tuple[str | None, int]:
    if isinstance(step.items, list):
        return None, len(step.items)
    kind, n = step.items.split(":")
    return kind, int(n)


def estimate_seconds(recipe: Recipe) -> float:
    """A generous estimate of how long one play-through takes."""
    total = 0.0
    shown = 0
    for step in recipe.steps:
        match step:
            case ShowItems():
                shown = _shown(step)[1]
                total += shown * step.ms_each / 1000
            case Distractor() | Timer():
                total += step.seconds
            case Recall():
                total += 4 + (3 * shown if step.kind == "recognition" else 1.5 * shown)
            case Choice():
                total += 10
            case Rule():
                total += 2 * step.trials
            case React():
                total += step.trials * (step.deadline_ms / 1000 + 0.6)
            case Feedback():
                total += 3
    return total * recipe.repeat


def check_recipe(recipe: Recipe, ability_dims: set[str]) -> list[str]:
    """Rules beyond the schema: known skills, recall has something to recall, answers exist,
    something is scored, and it fits in three minutes. An empty list means it can run."""
    errors: list[str] = []
    unknown = sorted(set(recipe.dims) - ability_dims)
    if unknown:
        errors.append(f"dims: unknown or unscorable skills {unknown}")
    if any(not 0.0 < w <= 1.0 for w in recipe.dims.values()):
        errors.append("dims: each loading must be in (0, 1]")
    elif max(recipe.dims.values()) != 1.0:
        errors.append("dims: one skill must have loading 1.0")
    last: ShowItems | None = None
    for i, step in enumerate(recipe.steps):
        where = f"steps[{i}] {step.block}"
        match step:
            case ShowItems():
                kind, n = _shown(step)
                if kind is None and len(set(step.items)) != n:
                    errors.append(f"{where}: items repeat")
                if kind not in (None, "digits") and n > POOL[str(kind)]:
                    errors.append(f"{where}: at most {POOL[str(kind)]} {kind}")
                last = step
            case Recall():
                if last is None:
                    errors.append(f"{where}: nothing was shown before it")
                    continue
                kind, n = _shown(last)
                if step.kind != "ordered" and kind in (None, "digits"):
                    errors.append(
                        f"{where}: {kind or 'listed items'} can only be recalled in order"
                    )
                elif step.kind != "ordered" and 2 * n > POOL[str(kind)]:
                    errors.append(
                        f"{where}: too many {kind} to mix with new ones "
                        f"(max {POOL[str(kind)] // 2})"
                    )
            case Choice():
                if len(set(step.options)) != len(step.options):
                    errors.append(f"{where}: options repeat")
                if step.answer not in step.options:
                    errors.append(f"{where}: the answer is not one of the options")
            case Rule():
                if step.switch_after is not None and step.switch_after >= step.trials:
                    errors.append(f"{where}: switch_after must be below trials")
            case React():
                if step.target in step.distractors or len(set(step.distractors)) != len(
                    step.distractors
                ):
                    errors.append(
                        f"{where}: distractors must differ from the target and each other"
                    )
    if not any(s.block in SCORED for s in recipe.steps):
        errors.append("nothing to score: add recall, choice, rule or react")
    seconds = estimate_seconds(recipe)
    if seconds > MAX_SECONDS:
        errors.append(f"too long: about {seconds:.0f} s, the limit is {MAX_SECONDS} s")
    return errors


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def validate_recipe(raw: Any, ability_dims: set[str]) -> tuple[Recipe | None, list[str]]:
    """Parse and check an LLM answer (JSON text or a mapping): schema, rules, language."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        recipe = Recipe.model_validate(data)
    except json.JSONDecodeError as exc:
        return None, [f"not JSON: {exc.msg}"]
    except ValidationError as exc:
        return None, [f"schema: {list(e['loc'])}: {e['msg']}" for e in exc.errors()[:10]]
    errors = check_recipe(recipe, ability_dims)
    banned = {v.word for text in _strings(recipe.model_dump()) for v in find_banned(text)}
    errors += [f"banned word '{w}'" for w in sorted(banned)]
    return (recipe if not errors else None), errors
