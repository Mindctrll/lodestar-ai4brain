"""WP2.3: plan_next and monitor through the real graph (each monitor route, onboarding, the
check-up after a long break, goals)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.runner import SessionRunner
from backend.db import tables as t
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import RunnerFactory, new_user
from tests.backend.agent.test_graph import collect, interrupt_of, play

REGISTRY = load_registry()
CORE = REGISTRY.core_skills()


async def returning_user(engine: AsyncEngine, days_ago: float = 1.0, sigma: float = 0.5) -> UUID:
    """A user past onboarding: one scored round and a known profile, last seen `days_ago`."""
    user_id = await new_user(engine)
    then = datetime.now(UTC) - timedelta(days=days_ago)
    async with engine.begin() as conn:
        session_id = uuid4()
        await conn.execute(
            t.sessions.insert().values(
                session_id=session_id,
                user_id=user_id,
                trigger="ui",
                status="ended",
                started_at=then,
            )
        )
        await conn.execute(
            t.rounds.insert().values(
                round_id=uuid4(),
                user_id=user_id,
                session_id=session_id,
                game_id="echo",
                level=0.4,
                status="completed",
                started_at=then,
                scored_at=then,
            )
        )
        for dim in CORE | {"short_term_memory", "cognitive_flexibility", "numerical_thinking"}:
            await conn.execute(
                t.dimension_state.insert().values(
                    user_id=user_id, dim=dim, mu=0.0, sigma=sigma, n=40, last_practised=then
                )
            )
    return user_id


async def decisions(engine: AsyncEngine, session_id: UUID, node: str) -> list[Any]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(t.decisions.c.chosen, t.decisions.c.reason)
            .where(t.decisions.c.session_id == session_id, t.decisions.c.node == node)
            .order_by(t.decisions.c.ts)
        )
        return list(rows)


async def start(runner: SessionRunner, user_id: UUID) -> tuple[UUID, dict[str, Any]]:
    session_id = await runner.create_session(user_id, "ui")
    return session_id, interrupt_of(await collect(runner, user_id, session_id))


def stopped(spec: dict[str, Any], status: str = "stopped", reason: str = "user") -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "round_id": spec["round_id"],
        "game_id": spec["game_id"],
        "status": status,
        "stop_reason": reason,
        "trial_count": 0,
        "final_level": spec["level"],
        "started_at": now,
        "ended_at": now,
    }


async def test_uw1_onboarding_battery(make_runner: RunnerFactory, aengine: AsyncEngine) -> None:
    runner = await make_runner()
    user_id = await new_user(aengine)
    session_id, spec = await start(runner, user_id)
    played = []
    while True:
        played.append(spec["game_id"])
        assert spec["mode"] == "assess"
        events = await play(runner, aengine, user_id, session_id, spec, [True] * 8 + [False] * 2)
        if not any(e["kind"] == "interrupt" for e in events):
            break
        spec = interrupt_of(events)
    assert played == REGISTRY.batteries["onboarding"].games  # Quick Draw first
    reasons = [r.reason for r in await decisions(aengine, session_id, "plan_next")]
    assert reasons[0].startswith("Warm-up game 1 of 6")
    async with aengine.connect() as conn:
        sigmas = dict(
            (
                await conn.execute(
                    select(t.dimension_state.c.dim, t.dimension_state.c.sigma).where(
                        t.dimension_state.c.user_id == user_id
                    )
                )
            ).all()
        )
    assert all(sigmas[d] < 0.8 for d in CORE), sigmas


async def test_monitor_continue_then_budget_end(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id, spec = await start(runner, user_id)
    for i in range(3):
        events = await play(runner, aengine, user_id, session_id, spec, [True] * 8 + [False] * 2)
        if i < 2:
            spec = interrupt_of(events)
    verdicts = [r.chosen for r in await decisions(aengine, session_id, "monitor")]
    assert verdicts == ["continue", "continue", "end"]


async def test_monitor_eases_after_a_hard_round(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id, spec = await start(runner, user_id)
    events = await collect(
        runner, user_id, session_id, resume=stopped(spec, "eased", "frustration")
    )
    nxt = interrupt_of(events)
    [verdict] = await decisions(aengine, session_id, "monitor")
    assert verdict.chosen == "ease" and "lighter" in verdict.reason
    assert nxt["target_p"] == 0.9  # Chill: an easier next round


async def test_monitor_suggests_a_break_after_two_stopped_games(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id, spec = await start(runner, user_id)
    spec = interrupt_of(await collect(runner, user_id, session_id, resume=stopped(spec)))
    events = await collect(runner, user_id, session_id, resume=stopped(spec))
    assert not any(e["kind"] == "interrupt" for e in events)  # the session winds down
    assert [r.chosen for r in await decisions(aengine, session_id, "monitor")][-1] == "break"
    async with aengine.connect() as conn:
        status = (
            await conn.execute(
                select(t.sessions.c.status).where(t.sessions.c.session_id == session_id)
            )
        ).scalar_one()
    assert status == "ended"


async def test_monitor_stops_when_answers_slow_down(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id, spec = await start(runner, user_id)
    # Plant a tiring session: fast and right early, slow and wrong late.
    async with aengine.begin() as conn:
        rid = uuid4()
        await conn.execute(
            t.rounds.insert().values(
                round_id=rid, user_id=user_id, session_id=session_id, game_id="echo", level=0.4
            )
        )
        base = datetime.now(UTC) - timedelta(minutes=20)
        for i in range(30):
            late = i >= 20
            await conn.execute(
                t.trials.insert().values(
                    trial_id=uuid4(),
                    user_id=user_id,
                    session_id=session_id,
                    round_id=rid,
                    game_id="echo",
                    level=0.4,
                    trial_index=i,
                    correct=not (late and i % 2 == 0),
                    rt_ms=1400.0 + i if late else 500.0 + (i % 3) * 20,
                    stimulus={},
                    ts=base + timedelta(seconds=10 * i),
                )
            )
    await play(runner, aengine, user_id, session_id, spec, [True] * 8)
    [verdict] = await decisions(aengine, session_id, "monitor")
    assert verdict.chosen == "end" and "slowing down" in verdict.reason


async def test_uw15_check_up_after_three_weeks(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine, days_ago=21, sigma=0.45)
    session_id, spec = await start(runner, user_id)
    assert spec["mode"] == "assess"
    [plan] = await decisions(aengine, session_id, "plan_next")
    assert plan.reason.startswith("Welcome back. It's been 21 days")
    async with aengine.connect() as conn:
        view = (
            await conn.execute(
                select(t.dimension_state.c.sigma).where(
                    t.dimension_state.c.user_id == user_id,
                    t.dimension_state.c.dim == "working_memory",
                )
            )
        ).scalar_one()
    assert view == 0.45  # stored sigma is unchanged; drift is applied when it is read or scored


async def test_goal_raises_its_skill(make_runner: RunnerFactory, aengine: AsyncEngine) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine, days_ago=1)
    async with aengine.begin() as conn:
        await conn.execute(
            t.goals.insert().values(
                user_id=user_id,
                dim="working_memory",
                kind="range",
                target=0.1,
                due=date.today() + timedelta(days=12),
            )
        )
        # make every other skill a little less certain, so only the goal can explain the pick
        await conn.execute(
            update(t.dimension_state)
            .where(
                t.dimension_state.c.user_id == user_id, t.dimension_state.c.dim != "working_memory"
            )
            .values(sigma=0.55)
        )
    session_id, _ = await start(runner, user_id)
    [plan] = await decisions(aengine, session_id, "plan_next")
    assert plan.chosen.startswith("working_memory:") and "goal" in plan.reason
