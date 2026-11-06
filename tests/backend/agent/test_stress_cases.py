"""The six stress cases through the real graph: the button masher, the plateau, the "why" audit,
pushback, the fortune teller and the split profile."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.intents import classify
from backend.agent.slots import named_day
from backend.contracts.trial import TrialEvent
from backend.db import tables as t
from backend.db.twin_store import acs_counts, rebuild_twin, record_trials
from tests.backend.agent.conftest import RunnerFactory, new_user
from tests.backend.agent.test_graph import collect, interrupt_of, play
from tests.backend.agent.test_policy import returning_user


async def _set_skill(engine: AsyncEngine, user_id: UUID, dim: str, mu: float, sigma: float) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            t.dimension_state.delete().where(
                t.dimension_state.c.user_id == user_id, t.dimension_state.c.dim == dim
            )
        )
        await conn.execute(
            t.dimension_state.insert().values(
                user_id=user_id, dim=dim, mu=mu, sigma=sigma, n=200,
                last_practised=datetime.now(UTC) - timedelta(days=1),
            )
        )  # fmt: skip


async def _skill(engine: AsyncEngine, user_id: UUID, dim: str) -> tuple[float, float]:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(t.dimension_state.c.mu, t.dimension_state.c.sigma).where(
                    t.dimension_state.c.user_id == user_id, t.dimension_state.c.dim == dim
                )
            )
        ).one()
    return row.mu, row.sigma


def cards(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] == "card" and e["card"] == kind]


def said(events: list[dict[str, Any]]) -> str:
    return " ".join(e["text"] for e in events if e["kind"] == "say")


async def _mash(
    runner: Any, engine: AsyncEngine, user_id: UUID, session_id: UUID, spec: dict[str, Any]
) -> list[dict[str, Any]]:
    round_id, start = UUID(spec["round_id"]), datetime.now(UTC)
    trials = [
        TrialEvent(
            trial_id=uuid4(), round_id=round_id, session_id=session_id, game_id=spec["game_id"],
            level=spec["level"], trial_index=i, stimulus={}, correct=i % 3 == 0, rt_ms=90.0 + i,
            ts=start + timedelta(milliseconds=200 * i),
        )
        for i in range(12)
    ]  # fmt: skip
    async with engine.begin() as conn:
        await record_trials(conn, user_id, trials)
    return await collect(
        runner, user_id, session_id,
        resume={
            "round_id": str(round_id), "game_id": spec["game_id"], "status": "completed",
            "trial_count": 12, "final_level": spec["level"], "started_at": start.isoformat(),
            "ended_at": (start + timedelta(seconds=5)).isoformat(),
        },
    )  # fmt: skip


async def test_button_masher_flags_the_round_and_keeps_the_estimate(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    await _set_skill(aengine, user_id, "selective_attention", 0.5, 0.5)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id, message="play Arrow Storm"))
    events = await _mash(runner, aengine, user_id, session_id, spec)

    [card] = cards(events, "rushed")
    assert card["median_rt_ms"] < 150 and card["answered"] == 12
    mu, sigma = await _skill(aengine, user_id, "selective_attention")
    assert mu == pytest.approx(0.5, abs=0.02) and sigma > 0.5  # no drop, and less sure
    assert "Were you distracted, or rushing?" in said(events)
    async with aengine.connect() as conn:
        score = (
            await conn.execute(
                select(t.rounds.c.score).where(t.rounds.c.round_id == UUID(spec["round_id"]))
            )
        ).scalar_one()
    assert score is None
    # A fair retake comes next, and the rebuilt profile agrees with the live one.
    retake = interrupt_of(events)
    assert retake["game_id"] == spec["game_id"] and "didn't count" in retake["reason"]
    await rebuild_twin(aengine, user_id)


async def test_plateau_changes_the_format(make_runner: RunnerFactory, aengine: AsyncEngine) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    await _set_skill(aengine, user_id, "working_memory", 0.5, 0.45)
    today = datetime.now(UTC).date()
    async with aengine.begin() as conn:
        for i in range(8):
            await conn.execute(
                t.history.insert().values(
                    user_id=user_id, day=today - timedelta(days=3 * (7 - i)),
                    dim="working_memory", mu=0.5 + 0.01 * (i % 2), sigma=0.45, n=100 + 20 * i,
                )
            )  # fmt: skip
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id, message="play working memory")
    spec = interrupt_of(events)
    assert spec["track"] == "new_format"
    assert "stayed near" in spec["reason"] and "New approach" in spec["reason"]
    assert spec["game_id"] != "echo"  # echo is what they played last


async def test_every_pick_says_why_and_past_picks_can_be_asked_about(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    today = datetime.now(UTC).date()
    async with aengine.begin() as conn:
        for i in range(3):
            await conn.execute(
                t.history.insert().values(
                    user_id=user_id, day=today - timedelta(days=i), dim="working_memory",
                    mu=0.3 + i * 0.1, sigma=0.5, n=100,
                )
            )  # fmt: skip
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id, message="play working memory"))
    assert spec["reason"]
    assert any(line["source"] == "Progress curve" for line in spec["why"])

    events = await collect(
        runner, user_id, session_id, message="Why did you assign me this exercise today?"
    )
    [card] = cards(events, "why")
    assert card["lines"] and "[D1]" in said(events)

    await play(runner, aengine, user_id, session_id, spec, [True] * 6 + [False] * 2)
    events = await collect(runner, user_id, session_id, message="What did I play today?")
    assert "75%" in said(events)
    assert cards(events, "history")[0]["rows"][0]["score"] == 75


async def test_pushback_widens_the_range_and_counts_once(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    await _set_skill(aengine, user_id, "working_memory", 0.2, 0.5)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id, message="play Echo"))
    await play(runner, aengine, user_id, session_id, spec, [False] * 8 + [True] * 2)
    mu, sigma = await _skill(aengine, user_id, "working_memory")

    text = "That's not fair, the room was so noisy I could not focus"
    events = await collect(runner, user_id, session_id, message=text)
    assert not [e for e in events if e["kind"] == "interrupt" and e["payload"]["type"] == "confirm"]
    [card] = cards(events, "pushback")
    assert card["dims"][0]["after_high"] - card["dims"][0]["after_low"] > (
        card["dims"][0]["before_high"] - card["dims"][0]["before_low"]
    )
    mu2, sigma2 = await _skill(aengine, user_id, "working_memory")
    assert mu2 == pytest.approx(mu) and sigma2 > sigma
    async with aengine.connect() as conn:
        counts = await acs_counts(conn, user_id)
        logged = (
            await conn.execute(
                select(t.events.c.payload).where(
                    t.events.c.user_id == user_id, t.events.c.type == "assessment.contested"
                )
            )
        ).all()
    assert counts["V"] == (1, 1) and counts["I"][0] >= 1 and len(logged) == 1

    again = await collect(runner, user_id, session_id, message="I disagree, I was interrupted")
    assert "already" in said(again)
    async with aengine.connect() as conn:
        assert (await acs_counts(conn, user_id))["V"] == (1, 1)  # the reward isn't farmed


async def test_fortune_teller_gets_a_range_never_a_number(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(
        runner, user_id, session_id, message="What exactly will my cognitive score be next month?"
    )
    text = said(events)
    assert "can't give you an exact number" in text
    assert not cards(events, "forecast") or "likely between" in text


async def test_split_profile_gets_two_tracks(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    await _set_skill(aengine, user_id, "reasoning", 3.0, 0.4)
    await _set_skill(aengine, user_id, "selective_attention", -3.0, 0.4)
    session_id = await runner.create_session(user_id, "ui")
    first = interrupt_of(await collect(runner, user_id, session_id))
    assert first["track"] == "foundation" and first["target_p"] == 0.9
    assert "far apart" in first["reason"]
    second = interrupt_of(await play(runner, aengine, user_id, session_id, first, [True] * 10))
    assert second["track"] == "advanced" and second["target_p"] == 0.65
    assert second["level"] > first["level"] + 0.3  # two difficulties, never one average


@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("What exactly will my cognitive score be next month?", "forecast_range"),
        ("will my memory be better in a month", "forecast_range"),
        ("I disagree, I got distracted by my phone", "contest"),
        ("That result doesn't reflect me, it was too noisy", "contest"),
        ("Why did you assign me this specific exercise today?", "explain"),
        ("what did I play yesterday", "session_history"),
    ],
)
def test_the_questions_are_routed_without_a_model(text: str, tool: str) -> None:
    routed = classify(text, "ui")
    assert routed.sure and routed.intent.tool == tool


def test_named_days() -> None:
    friday = date(2026, 11, 6)
    assert named_day("yesterday", friday) == date(2026, 11, 5)
    assert named_day("on tuesday", friday) == date(2026, 11, 3)
    assert named_day("3 days ago", friday) == date(2026, 11, 3)
    assert named_day("on friday", friday) == date(2026, 10, 30)
    assert named_day("no day", friday) is None


async def test_a_new_user_has_nothing_to_contest(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await new_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id, message="that's not fair")
    assert "no round" in said(events)
