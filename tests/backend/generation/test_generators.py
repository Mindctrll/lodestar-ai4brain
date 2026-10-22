import random

import pytest

from backend.generation.generators.market_list import MarketListGenerator, WordList
from backend.generation.generators.market_rush import MarketLines, MarketRushGenerator
from backend.generation.generators.pattern_gap import Hints, PatternGapGenerator, _HintSets
from backend.generation.generators.registry import GENERATORS
from backend.generation.generators.spot_the_mistake import (
    SpotMistakeGenerator,
    StepTexts,
    step_errors,
)
from backend.registry.loader import load_registry

REGISTRY = load_registry()


@pytest.mark.parametrize("game_id", sorted(GENERATORS))
def test_code_built_content_is_always_valid(game_id: str) -> None:
    gen = GENERATORS[game_id]
    game = REGISTRY.game(game_id)
    for seed in range(15):
        for level in (0.0, 0.3, 0.6, 1.0):
            knobs = game.knobs_at(level)
            content = gen.build(knobs, random.Random(seed), None)
            assert gen.check(content, knobs) == [], (game_id, seed, level)
            gen.schema.model_validate(content.model_dump())


def test_market_rush_follows_the_knobs() -> None:
    gen = MarketRushGenerator()
    knobs = {"customers": 3, "items_per_order": 4, "change_rate": 0.4}
    c = gen.build(knobs, random.Random(1), "spices")
    assert c.theme == "spices"
    assert all(len(s.orders) == 3 and all(len(o.items) == 4 for o in s.orders) for s in c.scenes)
    assert all(len(s.changes) == 2 for s in c.scenes)  # round(0.4 * 3 * 4 / 2)


def test_market_lines_must_name_every_item() -> None:
    gen = MarketRushGenerator()
    knobs = {"customers": 1, "items_per_order": 2, "change_rate": 0.0}
    c = gen.build(knobs, random.Random(2), "fruit")
    bad = gen.apply_text(c, MarketLines(lines=["Just some bread please."] * 4))
    assert any("leaves out" in e for e in gen.check(bad, knobs))
    good_lines = [f"Hi! {' and '.join(o.items)}, please." for s in c.scenes for o in s.orders]
    assert gen.check(gen.apply_text(c, MarketLines(lines=good_lines)), knobs) == []


def test_market_list_custom_theme_uses_llm_words() -> None:
    gen = MarketListGenerator()
    knobs = {"list_length": 5}
    c = gen.build(knobs, random.Random(3), "volcanoes")
    assert gen.text_request(c) is not None  # no curated list: ask the LLM
    words = ["lava", "crater", "ash", "magma", "eruption", "smoke", "rock", "heat", "cone", "vent",
             "Lava", "two words", "x"]  # fmt: skip
    filled = gen.apply_text(c, WordList(words=words))
    assert gen.check(filled, knobs) == []
    assert gen.text_request(gen.build(knobs, random.Random(3), "football")) is None


def test_pattern_gap_hints_must_not_give_the_answer() -> None:
    gen = PatternGapGenerator()
    c = gen.build({"rules": 2}, random.Random(4), None)
    leaky = _HintSets(
        puzzles=[Hints(hints=["Look at rows.", "Think.", "The answer is option 2."])] * 6
    )
    assert any("gives the answer away" in e for e in gen.check(gen.apply_text(c, leaky), {}))


def test_spot_the_mistake_errors_are_real_and_numbers_kept() -> None:
    gen = SpotMistakeGenerator()
    c = gen.build({"steps": 4, "error_subtlety": 0.9}, random.Random(5), None)
    for p in c.puzzles:
        assert step_errors(p) == ([p.error_step] if p.has_error else [])
    texts = StepTexts(
        puzzles=[[s.text.replace(str(s.result), "999") for s in p.steps] for p in c.puzzles]
    )
    assert any("lost the number" in e for e in gen.check(gen.apply_text(c, texts), {}))


def test_planted_error_share_is_about_seventy_percent() -> None:
    gen = SpotMistakeGenerator()
    puzzles = [
        p for s in range(200) for p in gen.build({"steps": 3}, random.Random(s), None).puzzles
    ]
    share = sum(p.has_error for p in puzzles) / len(puzzles)
    assert 0.65 < share < 0.75
