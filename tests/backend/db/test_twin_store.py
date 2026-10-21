import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from psycopg.types.range import Range
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.api.deps import engine_dep
from backend.api.main import app
from backend.contracts.exercise import RoundResult
from backend.contracts.trial import TrialEvent
from backend.db import tables as t
from backend.db.engine import libpq_url, sync_url
from backend.db.twin_store import (
    NOTIFY_CHANNEL,
    ForeignRound,
    RoundNotFound,
    create_user,
    read_twin,
    rebuild_twin,
    record_trials,
    score_round_tx,
    start_round,
)
from backend.registry.loader import load_registry
from backend.scoring.rounds import ANSWERS_PER_ROUND

T0 = datetime(2026, 10, 21, 19, 0, tzinfo=UTC)
REGISTRY = load_registry()


@pytest.fixture
async def aengine(db_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(sync_url(db_url))
    yield engine
    await engine.dispose()


def _trials(
    round_id: UUID, session_id: UUID, results: list[bool], game_id: str = "echo"
) -> list[TrialEvent]:
    return [
        TrialEvent(
            trial_id=uuid4(), round_id=round_id, session_id=session_id, game_id=game_id,
            level=0.4, trial_index=i, stimulus={"i": i}, correct=c, rt_ms=650.0,
            ts=T0 + timedelta(seconds=5 * i),
        )
        for i, c in enumerate(results)
    ]  # fmt: skip


def _result(round_id: UUID, n: int, game_id: str = "echo") -> RoundResult:
    return RoundResult(
        round_id=round_id, game_id=game_id, status="completed", trial_count=n,
        final_level=0.4, started_at=T0, ended_at=T0 + timedelta(minutes=2),
    )  # fmt: skip


async def _played_round(
    engine: AsyncEngine, user_id: UUID, results: list[bool], game_id: str = "echo"
) -> UUID:
    round_id, session_id = uuid4(), uuid4()
    async with engine.begin() as conn:
        await start_round(conn, user_id=user_id, session_id=session_id, round_id=round_id,
                          game_id=game_id, level=0.4)  # fmt: skip
        await conn.execute(
            t.rounds.update().where(t.rounds.c.round_id == round_id).values(started_at=T0)
        )
        await record_trials(conn, user_id, _trials(round_id, session_id, results, game_id))
    return round_id


async def _new_user(engine: AsyncEngine) -> UUID:
    async with engine.begin() as conn:
        user_id, _ = await create_user(conn)
    return user_id


async def _projections(engine: AsyncEngine, user_id: UUID) -> tuple[list[Any], list[Any]]:
    async with engine.connect() as conn:
        state = (
            await conn.execute(
                select(
                    t.dimension_state.c.dim,
                    t.dimension_state.c.mu,
                    t.dimension_state.c.sigma,
                    t.dimension_state.c.n,
                    t.dimension_state.c.last_practised,
                    t.dimension_state.c.last_event_id,
                )
                .where(t.dimension_state.c.user_id == user_id)
                .order_by(t.dimension_state.c.dim)
            )
        ).all()
        history = (
            await conn.execute(
                select(t.history)
                .where(t.history.c.user_id == user_id)
                .order_by(t.history.c.day, t.history.c.dim)
            )
        ).all()
    return [tuple(r) for r in state], [tuple(r) for r in history]


async def _count(engine: AsyncEngine, table: Any, user_id: UUID) -> int:
    async with engine.connect() as conn:
        query = select(func.count()).select_from(table).where(table.c.user_id == user_id)
        return int((await conn.execute(query)).scalar_one())


async def test_trials_are_idempotent_and_owned(aengine: AsyncEngine) -> None:
    alice, bob = await _new_user(aengine), await _new_user(aengine)
    round_id, session_id = uuid4(), uuid4()
    trials = _trials(round_id, session_id, [True, False, True])
    async with aengine.begin() as conn:
        await start_round(conn, user_id=alice, session_id=session_id, round_id=round_id,
                          game_id="echo", level=0.4)  # fmt: skip
        first = await record_trials(conn, alice, trials)
        again = await record_trials(conn, alice, trials)
    assert (first.accepted, again.accepted, again.duplicates) == (3, 0, 3)
    assert await _count(aengine, t.events, alice) == 3
    async with aengine.begin() as conn:
        with pytest.raises(ForeignRound):
            await record_trials(conn, bob, trials)
    async with aengine.begin() as conn:
        with pytest.raises(RoundNotFound):
            await record_trials(conn, alice, _trials(uuid4(), session_id, [True]))


async def test_scored_round_updates_the_twin_in_one_go(aengine: AsyncEngine) -> None:
    user_id = await _new_user(aengine)
    round_id = await _played_round(aengine, user_id, [True] * 10 + [False] * 2)
    scored = await score_round_tx(aengine, user_id, _result(round_id, 12), REGISTRY)
    assert scored is not None
    [change] = scored.changes
    assert change.dim == "working_memory" and change.mu_after > change.mu_before
    assert change.sigma_after < change.sigma_before
    state, history = await _projections(aengine, user_id)
    assert [s[0] for s in state] == ["working_memory"] and len(history) == 1
    async with aengine.connect() as conn:
        types = (await conn.execute(
            select(t.events.c.type).where(t.events.c.user_id == user_id)
        )).scalars().all()  # fmt: skip
        scored_at = (await conn.execute(
            select(t.rounds.c.scored_at).where(t.rounds.c.round_id == round_id)
        )).scalar_one()  # fmt: skip
        view = await read_twin(conn, user_id)
    assert sorted(set(types)) == ["round.completed", "trial.recorded", "twin.updated"]
    assert scored_at is not None
    [dim] = view.dims
    assert dim.percent_low < dim.percent < dim.percent_high


async def test_replaying_the_same_round_changes_nothing(aengine: AsyncEngine) -> None:
    user_id = await _new_user(aengine)
    round_id = await _played_round(aengine, user_id, [True] * 8 + [False] * 4)
    assert await score_round_tx(aengine, user_id, _result(round_id, 12), REGISTRY) is not None
    before = await _projections(aengine, user_id), await _count(aengine, t.events, user_id)
    assert await score_round_tx(aengine, user_id, _result(round_id, 12), REGISTRY) is None
    after = await _projections(aengine, user_id), await _count(aengine, t.events, user_id)
    assert before == after


async def test_parallel_writers_are_serialised(aengine: AsyncEngine) -> None:
    """Two tabs scoring at once: the advisory lock makes the second see the first's result."""
    user_id = await _new_user(aengine)
    r1 = await _played_round(aengine, user_id, [True] * 12)
    r2 = await _played_round(aengine, user_id, [True] * 6 + [False] * 6)
    a, b = await asyncio.gather(
        score_round_tx(aengine, user_id, _result(r1, 12), REGISTRY),
        score_round_tx(aengine, user_id, _result(r2, 12), REGISTRY),
    )
    assert a is not None and b is not None
    first, second = sorted([a, b], key=lambda s: str(s.twin_event_id))
    assert second.changes[0].mu_before == pytest.approx(first.changes[0].mu_after)
    state, _ = await _projections(aengine, user_id)
    assert state[0][3] == 24  # n counts both rounds: no lost update


async def test_rebuild_gives_identical_projections(aengine: AsyncEngine) -> None:
    user_id = await _new_user(aengine)
    for results, game in [([True] * 9 + [False] * 3, "echo"), ([True] * 12, "souk_rush"),
                          ([False] * 5 + [True] * 7, "echo")]:  # fmt: skip
        round_id = await _played_round(aengine, user_id, results, game)
        await score_round_tx(aengine, user_id, _result(round_id, 12, game), REGISTRY)
    original = await _projections(aengine, user_id)
    assert await rebuild_twin(aengine, user_id) == 3
    assert await _projections(aengine, user_id) == original


async def test_life_context_window_halves_the_update(aengine: AsyncEngine) -> None:
    """UW9 through the database: a round inside 'slept badly' moves mu about half as much."""
    deltas = []
    for flagged in (False, True):
        user_id = await _new_user(aengine)
        async with aengine.begin() as conn:  # an established profile, practised just now
            await conn.execute(t.dimension_state.insert().values(
                user_id=user_id, dim="working_memory", mu=0.0, sigma=0.6, n=40, last_practised=T0,
            ))  # fmt: skip
        if flagged:
            async with aengine.begin() as conn:
                await conn.execute(t.life_context.insert().values(
                    user_id=user_id, label="slept badly",
                    period=Range(T0 - timedelta(hours=2), T0 + timedelta(hours=12)), weight=0.5,
                ))  # fmt: skip
        round_id = await _played_round(aengine, user_id, [True] * 10 + [False] * 2)
        scored = await score_round_tx(aengine, user_id, _result(round_id, 12), REGISTRY)
        assert scored is not None
        deltas.append(scored.changes[0].mu_after - scored.changes[0].mu_before)
    # The practice credit (the prediction step) is the same either way: compare the evidence.
    assert REGISTRY.practice is not None
    credit = REGISTRY.practice.per_round.gain(1 + 40 / ANSWERS_PER_ROUND)
    evidence = [d - credit for d in deltas]
    # Each answer's step halves; over a round the total is a bit more than half, because the
    # full-weight path's uncertainty shrinks faster.
    assert 0.4 < evidence[1] / evidence[0] < 0.7


async def test_scoring_notifies_listeners(aengine: AsyncEngine, db_url: str) -> None:
    user_id = await _new_user(aengine)
    round_id = await _played_round(aengine, user_id, [True] * 12)
    async with await psycopg.AsyncConnection.connect(
        libpq_url(db_url), autocommit=True
    ) as listener:
        await listener.execute(f"LISTEN {NOTIFY_CHANNEL}")
        await score_round_tx(aengine, user_id, _result(round_id, 12), REGISTRY)
        note = await anext(listener.notifies(timeout=5))
    assert note.payload == str(user_id)


async def test_api_flow(aengine: AsyncEngine) -> None:
    app.dependency_overrides[engine_dep] = lambda: aengine
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = (await client.post("/users", json={"age_confirmed": True})).json()
            headers = {"Authorization": f"Bearer {created['token']}"}
            user_id = UUID(created["user_id"])
            round_id, session_id = uuid4(), uuid4()
            async with aengine.begin() as conn:
                await start_round(conn, user_id=user_id, session_id=session_id,
                                  round_id=round_id, game_id="echo", level=0.4)  # fmt: skip
            trials = [
                tr.model_dump(mode="json") for tr in _trials(round_id, session_id, [True] * 3)
            ]
            assert (await client.post("/events", json={"trials": trials})).status_code == 401
            ok = await client.post("/events", json={"trials": trials}, headers=headers)
            assert ok.json() == {"accepted": 3, "duplicates": 0}
            twin = await client.get("/twin", headers=headers)
            assert twin.status_code == 200 and twin.json()["dims"] == []
    finally:
        app.dependency_overrides.clear()


async def test_first_round_of_a_skill_starts_from_its_cold_start_prior(
    aengine: AsyncEngine,
) -> None:
    """A strong, well-measured speed estimate lifts where working memory starts (NCPT priors)."""
    user_id = await _new_user(aengine)
    async with aengine.begin() as conn:
        await conn.execute(
            t.dimension_state.insert().values(
                user_id=user_id, dim="processing_speed", mu=1.5, sigma=0.3, n=30,
                last_practised=T0,
            )
        )  # fmt: skip
    round_id = await _played_round(aengine, user_id, [True] * 6 + [False] * 6)
    scored = await score_round_tx(aengine, user_id, _result(round_id, 12), REGISTRY)
    assert scored is not None
    wm = next(c for c in scored.changes if c.dim == "working_memory")
    assert wm.mu_before > 0.2 and wm.sigma_before < 1.5


async def test_rounds_are_scored_with_the_calibrated_device_lag(aengine: AsyncEngine) -> None:
    """Quick Draw's tap-in-time taps set the device lag; the scored round records it (WP4.1)."""
    user_id = await _new_user(aengine)
    round_id = await _played_round(aengine, user_id, [True] * 12, game_id="quick_draw")
    taps = [
        TrialEvent(
            trial_id=uuid4(), round_id=round_id, session_id=uuid4(), game_id="quick_draw",
            level=0.4, trial_index=900 + i, practice=True,
            stimulus={"kind": "tap_in_time", "beat": i}, response={"offset_ms": 100 + 10 * (i % 3)},
            ts=T0 + timedelta(seconds=i),
        )
        for i in range(8)
    ]  # fmt: skip
    async with aengine.begin() as conn:
        await record_trials(conn, user_id, taps)
    scored = await score_round_tx(aengine, user_id, _result(round_id, 12, "quick_draw"), REGISTRY)
    assert scored is not None
    async with aengine.connect() as conn:
        payload = (await conn.execute(
            select(t.events.c.payload).where(t.events.c.event_id == scored.twin_event_id)
        )).scalar_one()  # fmt: skip
    assert payload["inputs"]["device_lag_ms"] == 110
