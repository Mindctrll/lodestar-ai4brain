"""The content pipeline against the database, with a fuzzing stub LLM (WP2.2 "Done when": 500
generations, zero invalid items served)."""

import json
import random
import re
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from uuid import UUID

import pytest
from langchain_core.messages import BaseMessage
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.contracts.llm import LlmSelection
from backend.db.engine import sync_url
from backend.db.twin_store import create_user
from backend.generation.generators.registry import GENERATORS
from backend.generation.pipeline import ContentService
from backend.llm.factory import LlmFactory
from backend.memory.store import MemoryStore
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import test_settings

REGISTRY = load_registry()
STUB = LlmSelection(mode="stub", provider="stub", model="stub")


def fuzzing_responder(seed: int):  # type: ignore[no-untyped-def]
    """Answers each content prompt correctly, slightly wrong, or with junk, at random."""
    rng = random.Random(seed)

    def respond(messages: Sequence[BaseMessage]) -> str:
        prompt = "\n".join(str(m.content) for m in messages)
        roll = rng.random()
        if roll < 0.1:
            return "not json at all"
        if "Orders (one list" in prompt:
            orders = json.loads(re.search(r"\): (\[\[.*\]\])", prompt).group(1))  # type: ignore[union-attr]
            lines = [f"Hello, {' and '.join(o)} please." for o in orders]
            if roll < 0.4:
                lines[0] = "Just one thing, thanks."  # leaves items out
            if roll < 0.3:
                lines[-1] = "My diagnosis says I need " + " and ".join(orders[-1]) + "."
            return json.dumps({"lines": lines})
        if "common, concrete English nouns" in prompt:
            words = ["lava", "crater", "ash", "magma", "smoke", "rock", "heat", "cone", "vent",
                     "peak", "steam", "dust", "glow", "flow", "basalt", "pumice", "fire", "cloud",
                     "ridge", "slope", "boulder", "summit", "plume", "vent"]  # fmt: skip
            if roll < 0.4:
                words = words[:3]
            return json.dumps({"words": words})
        if "three hints" in prompt:
            n = prompt.count("attribute") // 1 or 6
            hint = ["Look across a row.", "Compare shapes.", "Check what repeats."]
            if roll < 0.4:
                hint[2] = "The answer is option 3."
            return json.dumps({"puzzles": [{"hints": hint}] * max(6, n)})
        if "Steps per puzzle" in prompt:
            steps = json.loads(re.search(r"Steps per puzzle: (\[.*\])", prompt).group(1))  # type: ignore[union-attr]
            if roll < 0.4:
                steps = [[re.sub(r"\d+", "7", s) for s in p] for p in steps]  # changes numbers
            return json.dumps({"puzzles": [[f"So, {s}" for s in p] for p in steps]})
        return "{}"

    return respond


@pytest.fixture
async def aengine(db_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(sync_url(db_url))
    yield engine
    await engine.dispose()


async def _user(engine: AsyncEngine) -> UUID:
    async with engine.begin() as conn:
        user_id, _ = await create_user(conn)
    return user_id


async def test_500_fuzzed_generations_never_serve_invalid_content(aengine: AsyncEngine) -> None:
    llm = LlmFactory(REGISTRY, test_settings(), aengine, stub_responder=fuzzing_responder(7))
    service = ContentService(aengine, llm, live_llm="always")
    user = await _user(aengine)
    rng = random.Random(11)
    sources: Counter[str] = Counter()
    games = sorted(GENERATORS)
    for i in range(500):
        game_id = games[i % len(games)]
        level = rng.random()
        knobs = REGISTRY.game(game_id).knobs_at(level)
        theme = rng.choice([None, "volcanoes", "fruit", "football"])
        prepared = await service.prepare(
            user_id=user, selection=STUB, game_id=game_id, level=level, knobs=knobs,
            seed=rng.randrange(2**31), theme=theme,
        )  # fmt: skip
        assert prepared is not None
        gen = GENERATORS[game_id]
        content = gen.schema.model_validate(prepared.content)
        assert await service.validate(gen, content, knobs, None) == [], (game_id, prepared.source)
        sources[prepared.source] += 1
    # The fuzzer breaks some answers, so both paths are exercised.
    assert sources["generated"] > 50 and sources["code"] > 50


async def test_pool_fill_and_take_never_repeats_for_a_user(aengine: AsyncEngine) -> None:
    service = ContentService(aengine, llm=None)
    game = REGISTRY.game("pattern_gap")
    added = await service.fill_pool(
        "pattern_gap", per_level=2, levels=(0.5,), knobs_at=game.knobs_at, seed=99
    )
    assert added == 2
    assert (
        await service.fill_pool("pattern_gap", per_level=2, levels=(0.5,), knobs_at=game.knobs_at)
        == 0
    )
    alice, bob = await _user(aengine), await _user(aengine)
    first = await service.take_from_pool(alice, "pattern_gap", 0.5)
    second = await service.take_from_pool(alice, "pattern_gap", 0.5)
    assert first and second and first.item_id != second.item_id
    assert await service.take_from_pool(alice, "pattern_gap", 0.5) is None  # pool used up for alice
    assert await service.take_from_pool(bob, "pattern_gap", 0.5) is not None


async def test_without_any_llm_play_still_gets_valid_content(aengine: AsyncEngine) -> None:
    service = ContentService(aengine, llm=None)
    user = await _user(aengine)
    prepared = await service.prepare(
        user_id=user, selection=STUB, game_id="souk_rush", level=0.5,
        knobs=REGISTRY.game("souk_rush").knobs_at(0.5), seed=1,
    )  # fmt: skip
    assert prepared is not None and prepared.source in ("code", "pool")
    assert await service.prepare(user_id=user, selection=STUB, game_id="echo", level=0.5,
                                 knobs={}, seed=1) is None  # fmt: skip


async def test_novelty_rejects_what_this_user_just_saw(
    aengine: AsyncEngine, memory: MemoryStore
) -> None:
    service = ContentService(aengine, llm=None, memory=memory)
    user = await _user(aengine)
    knobs = REGISTRY.game("market_list").knobs_at(0.5)
    first = await service.prepare(user_id=user, selection=STUB, game_id="market_list", level=0.5,
                                  knobs=knobs, seed=5, theme="kitchen")  # fmt: skip
    again = await service.prepare(user_id=user, selection=STUB, game_id="market_list", level=0.5,
                                  knobs=knobs, seed=5, theme="kitchen")  # fmt: skip
    assert first and again and first.content != again.content  # same seed, rebuilt for novelty
    assert "code_retries" in again.report
    other_user = await _user(aengine)
    other = await service.prepare(
        user_id=other_user, selection=STUB, game_id="market_list", level=0.5,
        knobs=knobs, seed=5, theme="kitchen",
    )  # fmt: skip
    assert other is not None and other.content == first.content


@pytest.mark.skipif(
    not __import__("os").environ.get("NAJMA_OLLAMA_TESTS"),
    reason="needs a local Ollama; set NAJMA_OLLAMA_TESTS=1 (slow on CPU)",
)
async def test_local_ollama_generations_are_valid_or_fall_back(aengine: AsyncEngine) -> None:
    """The same guarantee with a real local model: whatever it writes, nothing invalid is served."""
    import os

    settings = test_settings(ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    service = ContentService(aengine, LlmFactory(REGISTRY, settings, aengine), live_llm="always")
    local = LlmSelection(mode="local", provider="ollama", model=settings.local_model)
    user = await _user(aengine)
    runs = int(os.environ.get("NAJMA_OLLAMA_RUNS", "8"))
    sources: Counter[str] = Counter()
    for i in range(runs):
        game_id = sorted(GENERATORS)[i % len(GENERATORS)]
        knobs = REGISTRY.game(game_id).knobs_at(0.4)
        prepared = await service.prepare(
            user_id=user, selection=local, game_id=game_id, level=0.4, knobs=knobs, seed=i,
            theme="volcanoes" if game_id == "market_list" else None,
        )  # fmt: skip
        assert prepared is not None
        gen = GENERATORS[game_id]
        assert (
            await service.validate(gen, gen.schema.model_validate(prepared.content), knobs, None)
            == []
        )
        sources[prepared.source] += 1
    print(f"ollama sources over {runs} runs: {dict(sources)}")
