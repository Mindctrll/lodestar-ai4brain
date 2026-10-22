"""WP3.3 through the real graph: engagement risk eases the session, the fatigue point ends it
with a range, and the bandit feeds plan_next once there is data."""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.runner import SessionRunner
from backend.contracts.events import DimensionChange, ScoringInputs, TwinUpdated, TwinUpdatedPayload
from backend.db import tables as t
from backend.db.twin_store import append_event
from backend.ml import bandit
from backend.ml.engagement import FEATURES, EngagementModel
from backend.registry.loader import load_registry
from backend.scoring.levels import TARGET_P
from tests.backend.agent.conftest import RunnerFactory
from tests.backend.agent.test_graph import collect, interrupt_of, play
from tests.backend.agent.test_policy import decisions, returning_user

REGISTRY = load_registry()


def drifting_model() -> EngagementModel:
    """High risk when someone played on 1 day of the last 28, low from 2 days on."""
    coef = [0.0] * len(FEATURES)
    coef[FEATURES.index("active_28")] = -3.0
    return EngagementModel(
        version="test",
        mean=[0.0] * len(FEATURES),
        scale=[1.0] * len(FEATURES),
        coef=coef,
        intercept=4.5,
        grid=[-10.0, -1.0, 1.0, 10.0],
        p0=[0.0, 0.2, 0.6, 0.95],
        p1=[0.05, 0.25, 0.65, 1.0],
    )


def with_engagement(runner: SessionRunner) -> SessionRunner:
    runner.services = dataclasses.replace(runner.services, engagement=drifting_model())
    return runner


async def test_someone_drifting_away_gets_a_short_easy_session(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = with_engagement(await make_runner())
    user_id = await returning_user(aengine, days_ago=40)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    [pick] = await decisions(aengine, session_id, "plan_next")
    assert "A short, easy session today" in pick.reason
    assert REGISTRY.game(spec["game_id"]).duration_s <= 60
    assert spec["target_p"] == TARGET_P["chill"]
    assert "Welcome back" not in pick.reason  # the check-up waits
    events = await play(runner, aengine, user_id, session_id, spec, [True] * 10)
    events = await play(runner, aengine, user_id, session_id, interrupt_of(events), [True] * 10)
    verdicts = [r.chosen for r in await decisions(aengine, session_id, "monitor")]
    assert verdicts == ["continue", "end"]  # two rounds and done
    assert not any(e["kind"] == "interrupt" for e in events)


async def test_someone_playing_regularly_gets_the_usual_session(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = with_engagement(await make_runner())
    user_id = await returning_user(aengine, days_ago=1)
    session_id = await runner.create_session(user_id, "ui")
    await collect(runner, user_id, session_id)
    [pick] = await decisions(aengine, session_id, "plan_next")
    assert "short, easy" not in pick.reason


async def seed_tiring_sessions(engine: AsyncEngine, user_id: UUID, sessions: int = 4) -> None:
    """Past sessions whose answers slow down about 5 minutes in."""
    rng = np.random.default_rng(7)
    async with engine.begin() as conn:
        for s in range(sessions):
            start = datetime.now(UTC) - timedelta(days=s + 2)
            session_id, round_id = uuid4(), uuid4()
            await conn.execute(
                t.sessions.insert().values(
                    session_id=session_id, user_id=user_id, trigger="ui", status="ended",
                    started_at=start,
                )
            )  # fmt: skip
            await conn.execute(
                t.rounds.insert().values(
                    round_id=round_id, user_id=user_id, session_id=session_id,
                    game_id="quick_draw", level=0.4, started_at=start, status="completed",
                )
            )  # fmt: skip
            await conn.execute(t.trials.insert(), [
                {"trial_id": uuid4(), "user_id": user_id, "session_id": session_id,
                 "round_id": round_id, "game_id": "quick_draw", "level": 0.4, "trial_index": i,
                 "correct": bool(rng.random() < (0.6 if i >= 30 else 0.9)),
                 "rt_ms": float(np.exp(rng.normal(np.log(450) + (0.7 if i >= 30 else 0), 0.2))),
                 "stimulus": {}, "ts": start + timedelta(seconds=10 * i)}
                for i in range(60)
            ])  # fmt: skip


async def test_the_fatigue_point_ends_a_session_with_a_range(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    await seed_tiring_sessions(aengine, user_id)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    config = runner.config(session_id)
    state = (await runner.graph.aget_state(config)).values
    point = state["fatigue_point"]
    assert 4 <= point.median <= 6 and state["budget"].fatigue_point_min == point.median
    # Twenty minutes have passed: past this person's usual point.
    await runner.graph.aupdate_state(
        config, {"started_at": datetime.now(UTC) - timedelta(minutes=20)}
    )
    await play(runner, aengine, user_id, session_id, spec, [True] * 10)
    [verdict] = await decisions(aengine, session_id, "monitor")
    assert verdict.chosen == "end"
    assert "usually start to slow down" in verdict.reason and " to " in verdict.reason


async def seed_gains(engine: AsyncEngine, user_id: UUID, rounds: int) -> None:
    """Rounds of Echo and Market Rush with their twin.updated events."""
    async with engine.begin() as conn:
        session_id = uuid4()
        start = datetime.now(UTC) - timedelta(days=3)
        await conn.execute(
            t.sessions.insert().values(
                session_id=session_id, user_id=user_id, trigger="ui", status="ended",
                started_at=start,
            )
        )  # fmt: skip
        mu = 0.0
        for i in range(rounds):
            round_id = uuid4()
            game = "echo" if i % 2 else "market_rush"
            when = start + timedelta(minutes=2 * i)
            await conn.execute(
                t.rounds.insert().values(
                    round_id=round_id, user_id=user_id, session_id=session_id, game_id=game,
                    level=0.4, started_at=when, status="completed", scored_at=when,
                )
            )  # fmt: skip
            change = DimensionChange(
                dim="working_memory", mu_before=mu, mu_after=mu + 0.05, sigma_before=0.5,
                sigma_after=0.48, n_after=10 * (i + 1),
            )  # fmt: skip
            mu += 0.05
            inputs = ScoringInputs(context_weight=1.0, trust=1.0, quality_verdict="ok")
            await append_event(
                conn,
                TwinUpdated(
                    user_id=user_id, session_id=session_id, ts=when,
                    payload=TwinUpdatedPayload(round_id=round_id, changes=[change], inputs=inputs),
                ),
            )  # fmt: skip


def bandit_parts(pick: Any) -> list[float]:
    return [c["breakdown"]["bandit_gain"] for c in pick]


async def test_the_bandit_joins_plan_next_once_there_is_data(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    bandit._population.clear()
    runner = await make_runner()
    fresh = await returning_user(aengine)
    session_id = await runner.create_session(fresh, "ui")
    await collect(runner, fresh, session_id)
    assert set(bandit_parts(await candidates(aengine, session_id))) == {0.0}

    played = await returning_user(aengine)
    await seed_gains(aengine, played, 12)
    async with aengine.connect() as conn:
        gains = await bandit.gains_by_game(conn, played, REGISTRY)
    assert set(gains) == {"echo", "market_rush"} and sum(map(len, gains.values())) == 11
    session_id = await runner.create_session(played, "ui")
    await collect(runner, played, session_id)
    parts = bandit_parts(await candidates(aengine, session_id))
    assert any(p > 0 for p in parts) and all(0 <= p <= 1 for p in parts)  # scaled to 0-1


async def candidates(engine: AsyncEngine, session_id: UUID) -> list[dict[str, Any]]:
    from sqlalchemy import select

    async with engine.connect() as conn:
        rows: list[dict[str, Any]] = (
            await conn.execute(
                select(t.decisions.c.candidates).where(
                    t.decisions.c.session_id == session_id, t.decisions.c.node == "plan_next"
                )
            )
        ).scalar_one()
    return rows
