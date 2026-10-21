"""WP3.1: Callback recalls this session's Market List once its delay has passed."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.context import NajmaContext, Services
from backend.agent.nodes.play import plan_next, prepare_exercise
from backend.agent.state import NajmaState
from backend.contracts.exercise import RoundResult
from backend.contracts.llm import LlmSelection
from backend.contracts.session import Intent
from backend.contracts.trial import TrialEvent
from backend.db.twin_store import record_trials, start_round
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import new_user

REGISTRY = load_registry()
WORDS = ["figs", "mint", "bread"]


async def market_list(
    engine: AsyncEngine, user_id: UUID, session_id: UUID, minutes_ago: float
) -> RoundResult:
    """A Market List round played `minutes_ago`, its words stored in shuffled order."""
    round_id, ended = uuid4(), datetime.now(UTC) - timedelta(minutes=minutes_ago)
    trials = [
        TrialEvent(
            trial_id=uuid4(), round_id=round_id, session_id=session_id, game_id="market_list",
            level=0.3, trial_index=i, stimulus={"word": WORDS[pos], "position": pos,
                                                "list_length": 3},
            correct=True, ts=ended,
        )
        for i, pos in enumerate([2, 0, 1])
    ]  # fmt: skip
    async with engine.begin() as conn:
        await start_round(
            conn, user_id=user_id, session_id=session_id, round_id=round_id,
            game_id="market_list", level=0.3,
        )  # fmt: skip
        await record_trials(conn, user_id, trials)
    return RoundResult(
        round_id=round_id, game_id="market_list", status="completed", trial_count=3,
        final_level=0.3, started_at=ended - timedelta(minutes=1), ended_at=ended,
    )  # fmt: skip


async def setup(engine: AsyncEngine, minutes_ago: float) -> tuple[Any, NajmaState]:
    user_id, session_id = await new_user(engine), uuid4()
    ctx = NajmaContext(
        user_id=user_id, session_id=session_id, consent=frozenset(),
        llm=LlmSelection(mode="stub", provider="stub", model="stub"),
        services=Services(engine=engine, registry=REGISTRY, llm=None),  # type: ignore[arg-type]
    )  # fmt: skip
    state = NajmaState(
        user_id=str(user_id), session_id=str(session_id), trigger="ui", persona="zitouna",
        rounds=[await market_list(engine, user_id, session_id, minutes_ago)],
    )  # fmt: skip
    return SimpleNamespace(context=ctx, store=None), state


async def test_callback_is_offered_after_the_delay_with_the_sessions_words(
    aengine: AsyncEngine,
) -> None:
    runtime, state = await setup(aengine, minutes_ago=1)
    assert (await plan_next(state, runtime=runtime))["plan"].game_id != "callback"  # too soon

    runtime, state = await setup(aengine, minutes_ago=5)
    out = await plan_next(state, runtime=runtime)
    assert out["plan"].game_id == "callback"
    assert out["decisions"][0].reason.startswith("Earlier you learned a market list.")
    state = state.model_copy(update={"plan": out["plan"], "decisions": out["decisions"]})
    spec = (await prepare_exercise(state, runtime=runtime))["exercise"]
    assert spec.content == {"words": WORDS}


async def test_asking_for_callback_without_a_market_list_plays_market_list_first(
    aengine: AsyncEngine,
) -> None:
    runtime, state = await setup(aengine, minutes_ago=5)
    state = state.model_copy(
        update={"rounds": [], "intent": Intent(kind="play", game_id="callback")}
    )
    out = await plan_next(state, runtime=runtime)
    assert out["plan"].game_id == "market_list"
