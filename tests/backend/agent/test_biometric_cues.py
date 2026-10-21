"""WP3.5 / WP3.9: coarse camera and voice cues. Each needs its own switch, only the coarse number
is kept, it is fused at 0.3 at most, it can only add a break suggestion, and it never reaches the
profile (AGENTS.md rule 3)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.context import Services
from backend.api.deps import engine_dep
from backend.api.main import create_app
from backend.contracts.affect import BiometricCues
from backend.contracts.events import AffectBiometricCue
from backend.db import tables as t
from backend.db.consent_store import set_consent
from backend.db.twin_store import append_event, read_twin
from backend.llm.factory import LlmFactory
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import RunnerFactory
from tests.backend.agent.conftest import test_settings as settings
from tests.backend.agent.test_graph import collect, interrupt_of, play
from tests.backend.agent.test_policy import returning_user

REGISTRY = load_registry()


@pytest.fixture
async def client(aengine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    app: FastAPI = create_app(with_lifespan=False)
    app.state.services = Services(
        engine=aengine, registry=REGISTRY, llm=LlmFactory(REGISTRY, settings(), aengine)
    )
    app.dependency_overrides[engine_dep] = lambda: aengine
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_cues_need_their_own_switch_and_are_kept_coarse(
    client: httpx.AsyncClient, aengine: AsyncEngine
) -> None:
    created = (await client.post("/users", json={"age_confirmed": True, "consent": {}})).json()
    headers = {"Authorization": f"Bearer {created['token']}"}
    session_id = str(uuid4())
    async with aengine.begin() as conn:
        await conn.execute(
            t.sessions.insert().values(
                session_id=session_id, user_id=UUID(created["user_id"]), trigger="ui"
            )
        )
    camera = {"session_id": session_id, "strain_cue": 0.437}
    assert (await client.post("/affect/cues", json=camera, headers=headers)).status_code == 409
    await client.put("/consent/camera", json={"granted": True}, headers=headers)
    assert (await client.post("/affect/cues", json=camera, headers=headers)).status_code == 204
    voice = {"session_id": session_id, "voice_strain_cue": 0.5}
    assert (await client.post("/affect/cues", json=voice, headers=headers)).status_code == 409
    empty = {"session_id": session_id}
    assert (await client.post("/affect/cues", json=empty, headers=headers)).status_code == 422
    other = (await client.post("/users", json={"age_confirmed": True, "consent": {}})).json()
    stranger = {"Authorization": f"Bearer {other['token']}"}
    assert (await client.post("/affect/cues", json=camera, headers=stranger)).status_code == 404
    async with aengine.connect() as conn:
        rows = (
            await conn.execute(
                select(t.events.c.payload).where(
                    t.events.c.session_id == UUID(session_id),
                    t.events.c.type == "affect.biometric.cue",
                )
            )
        ).all()
    assert [r.payload for r in rows] == [{"strain_cue": 0.4, "voice_strain_cue": None}]


async def _round(
    runner: Any, engine: AsyncEngine, cue: float | None
) -> tuple[list[dict[str, Any]], dict[str, Any], list[tuple[str, float, float]]]:
    """One Quick Draw round played with rapid taps (behaviour frustration 0.6), with or without
    a camera cue; returns the events, the logged affect reading and the profile afterwards."""
    async with engine.begin() as conn:  # same item difficulties for both users
        await conn.execute(
            delete(t.item_difficulty).where(t.item_difficulty.c.game_id == "quick_draw")
        )
    user_id = await returning_user(engine)
    async with engine.begin() as conn:
        await set_consent(conn, user_id, REGISTRY.consent, "camera", True)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id, message="play Quick Draw"))
    if cue is not None:
        async with engine.begin() as conn:
            await append_event(
                conn,
                AffectBiometricCue(
                    user_id=user_id,
                    session_id=session_id,
                    ts=datetime.now(UTC),
                    payload=BiometricCues(strain_cue=cue),
                ),
            )
    events = await play(
        runner, engine, user_id, session_id, spec, [True, False] * 5,
        behaviour={"rapid_taps": 3},
    )  # fmt: skip
    async with engine.connect() as conn:
        reading = (
            await conn.execute(
                select(t.events.c.payload).where(
                    t.events.c.user_id == user_id, t.events.c.type == "affect.estimated"
                )
            )
        ).scalar_one()
        twin = await read_twin(conn, user_id)
    return events, reading, sorted((d.dim, d.mu, d.sigma) for d in twin.dims)


async def test_a_cue_suggests_a_break_but_never_reaches_the_profile(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    calm_events, calm, calm_profile = await _round(runner, aengine, None)
    cue_events, cued, cued_profile = await _round(runner, aengine, 1.0)

    assert calm["sources"] == ["behaviour"] and calm["frustration_p"] == pytest.approx(0.6)
    assert cued["sources"] == ["behaviour", "camera"] and cued["behaviour_weight"] == 0.7
    assert cued["frustration_p"] == pytest.approx(0.72)  # 0.7 x 0.6 + 0.3 x 1
    verdicts = [
        [e["chosen"] for e in evs if e["kind"] == "decision" and e["node"] == "monitor"]
        for evs in (calm_events, cue_events)
    ]
    assert verdicts == [["continue"], ["break"]]  # a break suggestion, never "ease"

    assert [d for d, _, _ in calm_profile] == [d for d, _, _ in cued_profile]
    for (_, mu_a, sigma_a), (_, mu_b, sigma_b) in zip(calm_profile, cued_profile, strict=True):
        assert mu_a == pytest.approx(mu_b) and sigma_a == pytest.approx(sigma_b)
