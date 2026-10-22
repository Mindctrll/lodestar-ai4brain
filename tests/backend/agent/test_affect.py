"""Behaviour-based affect (WP2.9, docs/plan/12): the estimate rules, Lodestar easing off for a
frustrated player, the one-tap labels, and AGENTS.md rule 3 checked on real data: frustration
signals change what Lodestar does next, never the profile."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.affect import estimate
from backend.contracts.affect import BEHAVIOUR_WEIGHT_MIN, BehaviourSignals
from backend.contracts.exercise import RoundResult
from backend.db import tables as t
from backend.db.twin_store import read_twin
from tests.backend.agent.conftest import RunnerFactory
from tests.backend.agent.test_graph import collect, interrupt_of, play
from tests.backend.agent.test_policy import returning_user

FRUSTRATED = BehaviourSignals(error_streak=5, rapid_taps=4, rt_variability_z=2.5)


def _result(status: str = "completed", **kw: Any) -> RoundResult:
    now = datetime.now(UTC)
    return RoundResult(
        round_id=uuid4(), game_id="quick_draw", status=status, trial_count=10,  # type: ignore[arg-type]
        final_level=0.4, started_at=now, ended_at=now, **kw,
    )  # fmt: skip


def test_no_round_and_calm_play_read_as_calm() -> None:
    assert estimate(None, None, 0.0).frustration_p == 0.0
    calm = estimate(_result(behaviour=BehaviourSignals(error_streak=1)), 0.9, 0.1)
    assert calm.frustration_p < 0.5 and calm.fatigue_p == 0.1
    assert calm.sources == ["behaviour"] and calm.behaviour_weight == 1.0


@pytest.mark.parametrize(
    ("result", "accuracy", "at_least"),
    [
        (_result("eased"), 0.8, 0.8),
        (_result(behaviour=BehaviourSignals(mood="tough")), 0.8, 0.8),
        (_result(behaviour=BehaviourSignals(error_streak=4)), 0.8, 0.75),
        (_result(behaviour=BehaviourSignals(rapid_taps=3)), 0.8, 0.6),
        (_result(), 0.3, 0.6),
    ],
)
def test_frustration_signals(result: RoundResult, accuracy: float, at_least: float) -> None:
    assert estimate(result, accuracy, 0.0).frustration_p >= at_least


def test_slow_answers_read_as_fatigue() -> None:
    slow = estimate(_result(behaviour=BehaviourSignals(rt_z=2.0)), 0.8, 0.2)
    assert slow.fatigue_p == 0.6


def test_optional_cues_never_outweigh_behaviour() -> None:
    reading = estimate(_result(behaviour=BehaviourSignals()), 0.9, 0.0, cues=[("camera", 1.0)])
    assert reading.behaviour_weight == BEHAVIOUR_WEIGHT_MIN
    assert reading.frustration_p == pytest.approx(0.3)  # 0.7 x 0 + 0.3 x 1
    assert reading.sources == ["behaviour", "camera"]


async def test_frustrated_play_eases_off_and_is_logged(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    behaviour = FRUSTRATED.model_dump(mode="json")
    events = await play(
        runner, aengine, user_id, session_id, spec, [True] * 4 + [False] * 6, behaviour=behaviour
    )
    [monitor] = [e for e in events if e["kind"] == "decision" and e["node"] == "monitor"]
    assert monitor["chosen"] == "ease"
    async with aengine.connect() as conn:
        logged = (
            await conn.execute(
                select(t.events.c.payload).where(
                    t.events.c.user_id == user_id, t.events.c.type == "affect.estimated"
                )
            )
        ).scalar_one()
    assert logged["frustration_p"] >= 0.7


async def _profile_after(
    runner: Any, engine: AsyncEngine, behaviour: dict[str, Any] | None
) -> tuple[UUID, list[tuple[str, float, float]]]:
    # Learned item difficulty is shared across users: start both from the same items.
    async with engine.begin() as conn:
        await conn.execute(
            delete(t.item_difficulty).where(t.item_difficulty.c.game_id == "quick_draw")
        )
    user_id = await returning_user(engine)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id, message="play Quick Draw"))
    assert spec["game_id"] == "quick_draw"
    await play(runner, engine, user_id, session_id, spec, [True, False] * 5, behaviour=behaviour)
    async with engine.connect() as conn:
        twin = await read_twin(conn, user_id)
    return user_id, sorted((d.dim, d.mu, d.sigma) for d in twin.dims)


async def test_rule3_frustration_never_reaches_the_profile(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    _, calm = await _profile_after(runner, aengine, None)
    _, frustrated = await _profile_after(runner, aengine, FRUSTRATED.model_dump(mode="json"))
    assert [d for d, _, _ in calm] == [d for d, _, _ in frustrated]
    for (_, mu_a, sigma_a), (_, mu_b, sigma_b) in zip(calm, frustrated, strict=True):
        assert mu_a == pytest.approx(mu_b) and sigma_a == pytest.approx(sigma_b)
