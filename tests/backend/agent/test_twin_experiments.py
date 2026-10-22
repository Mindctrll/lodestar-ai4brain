"""WP3.2: talk to your Twin (UW8) and personal experiments (UW10)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.experiments import compare, result_facts, window_of
from backend.coach.verify import verify
from backend.db import tables as t
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import RunnerFactory
from tests.backend.agent.test_graph import collect, interrupt_of, play
from tests.backend.agent.test_policy import returning_user

REGISTRY = load_registry()
NAMES = [d.name for d in REGISTRY.dimensions]


def bad_drafts(messages: Any) -> str:
    return "You are definitely a night person, 100% sure."  # never passes: the template speaks


def said(events: list[dict[str, Any]]) -> str:
    return " ".join(e["text"] for e in events if e["kind"] == "say")


def test_comparison_and_its_facts() -> None:
    assert window_of(9) == "morning" and window_of(20) == "evening" and window_of(14) is None
    clear = compare([0.62, 0.66, 0.6], [0.84, 0.88, 0.9])
    assert clear.verdict == "evening" and clear.p_evening_better > 0.95
    assert clear.wins == clear.pairs == 9 and clear.low > 0
    close = compare([0.8, 0.7, 0.75], [0.74, 0.79, 0.72])
    assert close.verdict == "inconclusive"
    for comparison in (clear, close):
        packet, text = result_facts(comparison)
        assert verify(text, packet, NAMES, "willow").ok, text


async def seed_trials(
    engine: AsyncEngine, user_id: UUID, hour_utc: int, p: float, days: int
) -> None:
    """`days` sessions at a fixed time of day, 20 answers each, right with probability p."""
    rng = np.random.default_rng(hour_utc)
    async with engine.begin() as conn:
        for day in range(days):
            when = datetime.now(UTC).replace(hour=hour_utc, minute=0) - timedelta(days=day + 1)
            session_id, round_id = uuid4(), uuid4()
            await conn.execute(
                t.sessions.insert().values(
                    session_id=session_id,
                    user_id=user_id,
                    trigger="ui",
                    status="ended",
                    started_at=when,
                )
            )
            await conn.execute(
                t.rounds.insert().values(
                    round_id=round_id,
                    user_id=user_id,
                    session_id=session_id,
                    game_id="arrow_storm",
                    level=0.4,
                    status="completed",
                    started_at=when,
                    scored_at=when,
                    score=p,
                )
            )
            await conn.execute(t.trials.insert(), [
                {"trial_id": uuid4(), "user_id": user_id, "session_id": session_id,
                 "round_id": round_id, "game_id": "arrow_storm", "level": 0.4, "trial_index": i,
                 "correct": bool(rng.random() < p), "rt_ms": 500.0, "stimulus": {},
                 "ts": when + timedelta(seconds=5 * i)}
                for i in range(20)
            ])  # fmt: skip


async def test_uw8_twin_answers_when_im_sharpest(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner(bad_drafts)
    user_id = await returning_user(aengine)
    # Tunis is UTC+1: 07:00 UTC is morning there, 19:00 UTC is evening.
    await seed_trials(aengine, user_id, 7, 0.68, 12)
    await seed_trials(aengine, user_id, 19, 0.88, 12)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id, message="When am I sharpest?")
    reply = said(events)
    assert "best in the evening" in reply and "least well in the morning" in reply
    assert "[F" in reply and "100%" not in reply  # the unchecked draft never got through
    assert "chance the evening is really better" in reply
    assert not any(e["kind"] == "interrupt" for e in events)


async def test_uw8_unsure_twin_offers_an_experiment_and_yes_starts_it(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner(bad_drafts)
    user_id = await returning_user(aengine)
    await seed_trials(aengine, user_id, 7, 0.7, 2)
    await seed_trials(aengine, user_id, 19, 0.8, 2)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(
        runner, user_id, session_id, message="am I better in the morning or the evening?"
    )
    assert "not sure yet" in said(events) and "experiment" in said(events)
    events = await collect(runner, user_id, session_id, message="yes")
    [ask] = [e for e in events if e["kind"] == "interrupt"]
    assert ask["payload"]["tool"] == "start_experiment"
    assert "morning or the evening" in ask["payload"]["prompt"]


async def play_session(
    runner: Any, engine: AsyncEngine, user_id: UUID, local_hour: int, p: float, rng: Any
) -> list[dict[str, Any]]:
    session_id = await runner.create_session(user_id, "ui")
    start = datetime.now(UTC).replace(hour=local_hour - 1, minute=0)  # Tunis is UTC+1
    async with engine.begin() as conn:
        await conn.execute(
            update(t.sessions).where(t.sessions.c.session_id == session_id).values(started_at=start)
        )
    spec = interrupt_of(await collect(runner, user_id, session_id))
    events: list[dict[str, Any]] = []
    while True:
        assert (
            "Experiment session"
            in "".join(e.get("reason", "") for e in events if e["kind"] == "decision")
            or not events
        )
        results = [bool(rng.random() < p) for _ in range(12)]
        events = await play(runner, engine, user_id, session_id, spec, results)
        if not any(e["kind"] == "interrupt" for e in events):
            return events
        spec = interrupt_of(events)


async def test_uw10_experiment_finds_a_hidden_evening_advantage(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id, message="I want to run an experiment")
    [ask] = [e for e in events if e["kind"] == "interrupt"]
    assert ask["payload"]["tool"] == "start_experiment"
    await collect(runner, user_id, session_id, resume={"confirmed": True})
    rng = np.random.default_rng(3)
    last: list[dict[str, Any]] = []
    for day in range(6):  # alternating, as the plan says
        morning = day % 2 == 0
        last = await play_session(
            runner, aengine, user_id, 9 if morning else 20, 0.62 if morning else 0.9, rng
        )
    async with aengine.connect() as conn:
        row = (
            await conn.execute(select(t.experiments).where(t.experiments.c.user_id == user_id))
        ).one()
    assert row.status == "completed" and row.result["verdict"] == "evening"
    assert row.result["p_evening_better"] > 0.7
    assert "evening was better" in said(last) and "Probability evening is better" in said(last)
