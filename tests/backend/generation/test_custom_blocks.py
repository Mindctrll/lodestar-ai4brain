"""Custom games from blocks (WP3.7, docs/plan/08). "Done when": 50 LLM-written recipes, every
valid one runs (the browser half is frontend/src/games/custom_blocks/engine.test.ts), every
invalid one is rejected."""

import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml
from langchain_core.messages import BaseMessage
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.agent.context import Services
from backend.agent.graph import checkpointer, compile_graph
from backend.agent.intents import classify
from backend.agent.nodes.play import core_games_by_dim
from backend.agent.runner import SessionRunner
from backend.contracts.llm import LlmSelection
from backend.db import tables as t
from backend.db.engine import libpq_url, sync_url
from backend.db.twin_store import create_user
from backend.generation.blocks import Recipe, estimate_seconds, validate_recipe
from backend.generation.generators.custom_blocks import STARTERS, ability_dims
from backend.generation.pipeline import ContentService
from backend.generation.recipe_samples import BREAKS, FIXTURE, fixture_samples, render
from backend.llm.factory import LlmFactory
from backend.llm.stub import default_responder
from backend.registry.loader import load_registry
from backend.scoring.loadings import recipe_loadings
from tests.backend.agent.conftest import test_settings as settings_for_tests
from tests.backend.agent.test_graph import collect, interrupt_of, play
from tests.backend.agent.test_policy import returning_user

ROOT = Path(__file__).resolve().parents[3]
ROWS: list[dict[str, Any]] = yaml.safe_load((ROOT / FIXTURE).read_text(encoding="utf-8"))
REGISTRY = load_registry()
DIMS = ability_dims()
STUB = LlmSelection(mode="stub", provider="stub", model="stub")
PHONE_GAME = {
    "title": "Phone and Sums",
    "dims": {"numerical_thinking": 1.0, "working_memory": 0.5},
    "steps": [
        {"block": "show_items", "items": "digits:8", "ms_each": 700},
        {"block": "distractor", "task": "arithmetic:easy", "seconds": 10},
        {"block": "recall", "kind": "ordered"},
    ],
    "repeat": 3,
}


def test_the_fixture_is_what_the_generator_writes() -> None:
    if all(r["source"] == "fixture" for r in ROWS):
        assert (ROOT / FIXTURE).read_text(encoding="utf-8") == render(fixture_samples(), "fixture")


def test_50_recipes_every_invalid_one_is_rejected() -> None:
    assert len(ROWS) == 50
    for row in ROWS:
        recipe, errors = validate_recipe(row["recipe"], DIMS)
        assert (not errors) == row["valid"], (row["request"], errors)
        assert (recipe is not None) == row["valid"]
        assert row["served"] == (recipe.model_dump(mode="json") if recipe else None)
        if row["source"] == "fixture":
            assert row["valid"] == (row["broken"] is None), (row["broken"], errors)
    assert {r["broken"] for r in ROWS if r["broken"]} == set(BREAKS)  # every mistake is covered
    valid = [r for r in ROWS if r["valid"]]
    assert 20 <= len(valid) <= 40
    for row in valid:
        raw = row["recipe"]
        recipe = Recipe.model_validate(json.loads(raw) if isinstance(raw, str) else raw)
        assert estimate_seconds(recipe) <= 180


def test_starters_are_valid_recipes() -> None:
    for starter in STARTERS:
        assert validate_recipe(starter, DIMS)[1] == []


def test_block_games_count_a_little_and_only_when_asked() -> None:
    game = REGISTRY.game("custom_blocks")
    assert 0.3 <= game.effective_reliability <= 0.5  # docs/plan/07
    assert all(g.id != "custom_blocks" for gs in core_games_by_dim(REGISTRY).values() for g in gs)
    asked = classify(
        "Give me a game where I remember a phone number while doing maths.", "ui", REGISTRY
    )
    assert asked.intent.game_id == "custom_blocks" and asked.sure
    assert classify("give me a memory game", "ui", REGISTRY).intent.game_id is None


def test_recipe_loadings_keep_known_ability_skills_only() -> None:
    content = {"dims": {"reasoning": 1.0, "decision_style": 0.5, "telepathy": 0.5}}
    assert recipe_loadings(content, REGISTRY) == {"reasoning": 1.0}
    assert recipe_loadings({"dims": {"decision_style": 1.0}}, REGISTRY) is None


@pytest.fixture
async def aengine(db_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(sync_url(db_url))
    yield engine
    await engine.dispose()


def responder(recipe: Any):  # type: ignore[no-untyped-def]
    def respond(messages: Sequence[BaseMessage]) -> str:
        text = "\n".join(str(m.content) for m in messages)
        if "The player asked for" in text:
            return recipe if isinstance(recipe, str) else json.dumps(recipe)
        return default_responder(messages)

    return respond


@pytest.fixture
async def runner_with_content(db_url: str, aengine: AsyncEngine) -> AsyncIterator[Any]:
    pools: list[AsyncConnectionPool[Any]] = []

    async def build(recipe: Any) -> SessionRunner:
        pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
            libpq_url(db_url),
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await pool.open()
        pools.append(pool)
        llm = LlmFactory(REGISTRY, settings_for_tests(), aengine, stub_responder=responder(recipe))
        services = Services(
            engine=aengine, registry=REGISTRY, llm=llm, content=ContentService(aengine, llm)
        )
        return SessionRunner(compile_graph(checkpointer(pool)), services, "stub")

    yield build
    for pool in pools:
        await pool.close()


async def _beliefs(engine: AsyncEngine, user_id: UUID) -> dict[str, int]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(t.dimension_state.c.dim, t.dimension_state.c.n).where(
                t.dimension_state.c.user_id == user_id
            )
        )
        return {r.dim: r.n for r in rows}


async def test_a_requested_game_is_served_and_counts_for_its_recipe_skills(
    runner_with_content: Any, aengine: AsyncEngine
) -> None:
    runner = await runner_with_content(PHONE_GAME)
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(
        runner, user_id, session_id,
        message="Make me a game where I remember a phone number while doing maths",
    )  # fmt: skip
    spec = interrupt_of(events)
    assert spec["game_id"] == "custom_blocks"
    assert spec["content"]["steps"] == PHONE_GAME["steps"]
    assert spec["content"]["asked"].startswith("Make me a game")
    assert "only counting it a little" in spec["reason"]
    before = await _beliefs(aengine, user_id)
    await play(runner, aengine, user_id, session_id, spec, [True, True, False] * 8)
    after = await _beliefs(aengine, user_id)
    changed = {d for d in after if after[d] != before.get(d)}
    assert changed == {"numerical_thinking", "working_memory"}  # the recipe's, not the registry's


@pytest.mark.parametrize(
    "answer",
    [
        "Sure, here's a game!",  # not JSON
        {
            **PHONE_GAME,
            "repeat": 5,
            "steps": [*PHONE_GAME["steps"], {"block": "timer", "seconds": 30}],
        },
        {**PHONE_GAME, "steps": [{"block": "recall", "kind": "ordered"}]},
    ],
)
async def test_a_broken_recipe_is_never_served(aengine: AsyncEngine, answer: Any) -> None:
    llm = LlmFactory(REGISTRY, settings_for_tests(), aengine, stub_responder=responder(answer))
    service = ContentService(aengine, llm)
    async with aengine.begin() as conn:
        user_id, _ = await create_user(conn)
    prepared = await service.prepare(
        user_id=user_id, selection=STUB, game_id="custom_blocks", level=0.5, knobs={}, seed=3,
        request="a game where I remember a phone number while doing maths",
    )  # fmt: skip
    assert prepared is not None and prepared.source in ("code", "pool")
    assert (
        validate_recipe({k: v for k, v in prepared.content.items() if k != "asked"}, DIMS)[1] == []
    )
