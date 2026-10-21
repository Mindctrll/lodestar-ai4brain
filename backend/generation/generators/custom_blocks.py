"""Custom games from blocks (docs/plan/08): the user asks for a game, the LLM writes a recipe from
known blocks, code checks it, the browser's block engine runs it.

Without a request (or when the LLM fails), code serves one of the starter recipes below, so a
custom round never waits on a model.
"""

import random
from typing import Any, cast

from pydantic import BaseModel

from backend.contracts.common import Contract
from backend.generation.blocks import CustomGameContent, Recipe, check_recipe
from backend.generation.generators.base import TextRequest
from backend.registry.loader import load_registry

STARTERS: list[dict[str, Any]] = [
    {
        "title": "Number and Numbers",
        "dims": {"working_memory": 1.0},
        "steps": [
            {"block": "show_items", "items": "digits:6", "ms_each": 800},
            {"block": "distractor", "task": "arithmetic:easy", "seconds": 10},
            {"block": "recall", "kind": "ordered"},
        ],
        "repeat": 3,
    },
    {
        "title": "Star Catcher",
        "dims": {"processing_speed": 1.0, "inhibition": 0.3},
        "steps": [
            {
                "block": "react",
                "target": "★",
                "distractors": ["●", "■"],
                "deadline_ms": 900,
                "trials": 20,
            },
            {"block": "feedback", "level": "brief"},
        ],
        "repeat": 2,
    },
    {
        "title": "Rule Flip",
        "dims": {"cognitive_flexibility": 1.0},
        "steps": [
            {"block": "rule", "rule": "odd_even", "trials": 12, "switch_after": 4},
            {"block": "rule", "rule": "high_low", "trials": 12, "switch_after": 3},
            {"block": "feedback", "level": "full"},
        ],
    },
    {
        "title": "Seen It Before",
        "dims": {"short_term_memory": 1.0},
        "steps": [
            {"block": "show_items", "items": "words:6", "ms_each": 1000},
            {"block": "timer", "seconds": 5},
            {"block": "recall", "kind": "recognition"},
        ],
        "repeat": 2,
    },
]


def ability_dims() -> set[str]:
    return {d.id for d in load_registry().dimensions if not d.style}


class CustomBlocksGenerator:
    game_id = "custom_blocks"
    schema = CustomGameContent
    novelty = False  # a recipe is a game, not items; the items are drawn fresh every round

    def build(
        self, knobs: dict[str, float], rng: random.Random, theme: str | None
    ) -> CustomGameContent:
        return CustomGameContent.model_validate(rng.choice(STARTERS))

    def text_request(self, content: Contract) -> TextRequest | None:
        asked = cast(CustomGameContent, content).asked
        if not asked:
            return None
        dims = sorted(ability_dims())
        return TextRequest("custom_blocks", {"request": asked, "dims": dims}, Recipe, required=True)

    def apply_text(self, content: Contract, text: BaseModel) -> CustomGameContent:
        asked = cast(CustomGameContent, content).asked
        return CustomGameContent.model_validate({**text.model_dump(), "asked": asked})

    def check(self, content: Contract, knobs: dict[str, float]) -> list[str]:
        return check_recipe(cast(CustomGameContent, content), ability_dims())

    def signature(self, content: Contract) -> str:
        c = cast(CustomGameContent, content)
        return f"{c.title}: " + ", ".join(s.block for s in c.steps)
