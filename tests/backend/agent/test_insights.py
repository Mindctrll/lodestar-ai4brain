"""Insights, the coach switch and the model cards (docs/plan/10, 13; UW20)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.api.insights import PersonaInput, get_insights, headline, set_persona, wilson
from backend.db import tables as t
from tests.backend.agent.conftest import new_user


async def test_insights_calibration_and_rhythm(aengine: AsyncEngine) -> None:
    user_id = await new_user(aengine)
    now = datetime.now(UTC)
    session_id, round_id = uuid4(), uuid4()
    async with aengine.begin() as conn:
        await conn.execute(
            t.sessions.insert().values(
                session_id=session_id, user_id=user_id, trigger="ui", status="ended",
                started_at=now - timedelta(hours=1),
            )
        )  # fmt: skip
        await conn.execute(
            t.rounds.insert().values(
                round_id=round_id, user_id=user_id, session_id=session_id, game_id="quick_draw",
                level=0.5, status="completed", started_at=now - timedelta(hours=1),
            )
        )  # fmt: skip
        for i in range(12):
            await conn.execute(
                t.trials.insert().values(
                    trial_id=uuid4(), user_id=user_id, session_id=session_id, round_id=round_id,
                    game_id="quick_draw", level=0.5, trial_index=i, correct=i < 9,
                    rt_ms=400.0, confidence=0.9, stimulus={}, ts=now - timedelta(minutes=50),
                )
            )  # fmt: skip
    async with aengine.connect() as conn:
        view = await get_insights(user_id, conn, aengine)
    assert view.calibration is not None
    assert view.calibration.said == 0.9 and view.calibration.right == 0.75
    assert view.calibration.low < 0.75 < view.calibration.high  # a range, never a bare share
    assert view.fatigue is None  # one short session: nothing to plan around yet
    assert (view.rhythm.active_7, view.rhythm.sessions, view.rhythm.rounds) == (1, 1, 1)


async def test_switching_coach_writes_the_user_and_an_event(aengine: AsyncEngine) -> None:
    user_id = await new_user(aengine)
    await set_persona(PersonaInput(persona="spark"), user_id, aengine)
    async with aengine.connect() as conn:
        persona = (
            await conn.execute(select(t.users.c.persona).where(t.users.c.user_id == user_id))
        ).scalar_one()
        events = (
            await conn.execute(
                select(t.events.c.payload).where(
                    t.events.c.user_id == user_id, t.events.c.type == "settings.changed"
                )
            )
        ).all()
    assert persona == "spark"
    assert [e.payload["persona"] for e in events] == ["spark"]


def test_model_headlines_and_wilson() -> None:
    _, _, forecast = headline("growth_forecast", {"by_k": {"1": {"coverage": 0.79, "mae": 0.27}}})
    assert [h.value for h in forecast] == ["79%", "80%", "0.27 SD"]
    _, _, risk = headline(
        "engagement_risk",
        {"results": {"logistic regression": {"auc": 0.857, "ece": 0.006},
                     "days since last activity (rule)": {"auc": 0.828}}},
    )  # fmt: skip
    assert [h.value for h in risk] == ["0.86", "0.83", "0.006"]
    low, high = wilson(9, 12)
    assert 0 < low < 0.75 < high < 1
