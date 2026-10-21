"""What every content generator provides (docs/plan/08, "Who does what")."""

import random
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from backend.contracts.common import Contract


@dataclass(frozen=True)
class TextRequest:
    """The words an LLM may write for this content: a prompt and the schema of its answer."""

    prompt_name: str
    variables: dict[str, Any]
    schema: type[BaseModel]
    # True when only an LLM can serve the request (e.g. a theme with no curated word list).
    required: bool = False


class Generator(Protocol):
    @property
    def game_id(self) -> str: ...

    @property
    def schema(self) -> type[Contract]: ...

    def build(self, knobs: dict[str, float], rng: random.Random, theme: str | None) -> Contract:
        """Code-only content: structure, difficulty and plain-template text. Always valid."""
        ...

    def text_request(self, content: Contract) -> TextRequest | None:
        """What an LLM could write to make the text nicer, or None if nothing."""
        ...

    def apply_text(self, content: Contract, text: BaseModel) -> Contract:
        """Content with the LLM's text merged in (validated afterwards)."""
        ...

    def check(self, content: Contract, knobs: dict[str, float]) -> list[str]:
        """Content rules and solver checks; an empty list means valid."""
        ...

    def signature(self, content: Contract) -> str:
        """Text used for novelty checks against what this user saw recently."""
        ...


def count(knobs: dict[str, float], name: str, default: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, round(knobs.get(name, default))))
