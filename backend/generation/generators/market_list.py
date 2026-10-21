"""Market List: words flash, then you recall them. Themed lists (UW4: "a memory game about
football"); a theme we have no list for is filled by the LLM and checked for format."""

import random
import re
from typing import cast

from pydantic import BaseModel, Field

from backend.contracts.common import Contract
from backend.generation.generators.base import TextRequest, count
from backend.generation.schemas import MarketListContent
from backend.generation.vocab import themes, word_theme

LISTS = 2
_WORD = re.compile(r"^[a-z]{3,12}$")


class WordList(BaseModel):
    words: list[str] = Field(description="Common, concrete, single English words")


class MarketListGenerator:
    game_id = "market_list"
    schema = MarketListContent

    def _theme(self, theme: str | None, rng: random.Random) -> str:
        if theme:
            return theme.strip().lower()[:30]
        return str(rng.choice(sorted(themes()["word_themes"])))

    def build(
        self, knobs: dict[str, float], rng: random.Random, theme: str | None
    ) -> MarketListContent:
        chosen = self._theme(theme, rng)
        vocab = word_theme(chosen)
        if vocab is None:
            # No list for this theme yet: start from the market list; the LLM may replace it.
            vocab = word_theme("market") or []
        length = count(knobs, "list_length", 8, 3, 15)
        words = rng.sample(vocab, min(len(vocab), length * LISTS))
        return MarketListContent(
            theme=chosen, lists=[words[i * length : (i + 1) * length] for i in range(LISTS)]
        )

    def text_request(self, content: Contract) -> TextRequest | None:
        c = cast(MarketListContent, content)
        if word_theme(c.theme) is not None:
            return None  # a curated list needs no LLM
        n = sum(len(x) for x in c.lists) + 6
        return TextRequest("market_list", {"theme": c.theme, "count": n}, WordList, required=True)

    def apply_text(self, content: Contract, text: BaseModel) -> MarketListContent:
        c = cast(MarketListContent, content)
        seen: list[str] = []
        for word in cast(WordList, text).words:
            w = word.strip().lower()
            if _WORD.match(w) and w not in seen:
                seen.append(w)
        length = len(c.lists[0])
        if len(seen) < length * LISTS:
            return c.model_copy(update={"lists": [seen[:length], seen[length : 2 * length]]})
        return c.model_copy(
            update={"lists": [seen[i * length : (i + 1) * length] for i in range(LISTS)]}
        )

    def check(self, content: Contract, knobs: dict[str, float]) -> list[str]:
        c = cast(MarketListContent, content)
        errors: list[str] = []
        length = count(knobs, "list_length", 8, 3, 15)
        flat = [w for lst in c.lists for w in lst]
        for i, lst in enumerate(c.lists):
            if len(lst) != length:
                errors.append(f"list {i} has {len(lst)} words, expected {length}")
        bad = [w for w in flat if not _WORD.match(w)]
        if bad:
            errors.append(f"not simple lowercase words: {bad}")
        if len(set(flat)) != len(flat):
            errors.append("a word appears twice")
        curated = word_theme(c.theme)
        if curated is not None and not set(flat) <= set(curated):
            errors.append("words outside the curated theme list")
        return errors

    def signature(self, content: Contract) -> str:
        return " ".join(w for lst in cast(MarketListContent, content).lists for w in lst)
