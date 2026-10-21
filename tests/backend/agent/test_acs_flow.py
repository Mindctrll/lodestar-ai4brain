"""ACS through the real graph: verification from Spot the AI's Mistake, responsible use from a
suggested break (docs/plan/11; UW12)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.acs.score import score
from backend.db import tables as t
from backend.db.twin_store import acs_counts
from backend.generation.pipeline import ContentService
from tests.backend.agent.conftest import RunnerFactory
from tests.backend.agent.test_graph import collect, interrupt_of, play
from tests.backend.agent.test_policy import returning_user, stopped


async def test_spot_the_mistake_feeds_verification(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    runner.services = runner.services.__class__(
        **{**runner.services.__dict__, "content": ContentService(aengine, llm=None)}
    )
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id, message="play Spot the AI's Mistake")
    spec = interrupt_of(events)
    assert spec["game_id"] == "spot_the_mistake" and spec["content"]["puzzles"]
    await play(runner, aengine, user_id, session_id, spec, [True, True, False, True, True])
    async with aengine.connect() as conn:
        counts = await acs_counts(conn, user_id)
    assert counts["V"] == (4, 5)
    result = score(counts)  # type: ignore[arg-type]
    assert result.value is not None and result.components[0].enough


async def test_break_taken_or_not(make_runner: RunnerFactory, aengine: AsyncEngine) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    spec = interrupt_of(await collect(runner, user_id, session_id, resume=stopped(spec)))
    await collect(runner, user_id, session_id, resume=stopped(spec))  # two stopped: a break
    await runner.create_session(user_id, "ui")  # straight back: the break wasn't taken
    async with aengine.connect() as conn:
        assert (await acs_counts(conn, user_id))["R"] == (0, 1)
    # Another break, this time 15 minutes away before coming back.
    second = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, second))
    spec = interrupt_of(await collect(runner, user_id, second, resume=stopped(spec)))
    await collect(runner, user_id, second, resume=stopped(spec))
    async with aengine.begin() as conn:
        await conn.execute(update(t.sessions).where(t.sessions.c.session_id == second).values(
            ended_at=datetime.now(UTC) - timedelta(minutes=15)))  # fmt: skip
    await runner.create_session(user_id, "ui")
    async with aengine.connect() as conn:
        assert (await acs_counts(conn, user_id))["R"] == (1, 2)
