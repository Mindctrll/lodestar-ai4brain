"""WP2.5 read models: stat pills, heatmaps in the user's time zone, Twin curves with ranges,
recent decisions, a session trace, and the live "twin updated" stream."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.websockets import WebSocketDisconnect

from backend.agent.context import Services
from backend.api.deps import engine_dep
from backend.api.main import create_app
from backend.db import tables as t
from backend.db.engine import libpq_url
from backend.db.twin_store import NOTIFY_CHANNEL
from backend.llm.factory import LlmFactory
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import test_settings

REGISTRY = load_registry()


@pytest.fixture
def app(aengine: AsyncEngine) -> FastAPI:
    application = create_app(with_lifespan=False)
    application.state.services = Services(
        engine=aengine, registry=REGISTRY, llm=LlmFactory(REGISTRY, test_settings(), aengine)
    )
    application.dependency_overrides[engine_dep] = lambda: aengine
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def signup(
    client: httpx.AsyncClient, tz: str = "Africa/Tunis"
) -> tuple[UUID, dict[str, str]]:
    body = (await client.post("/users", json={"age_confirmed": True, "timezone": tz})).json()
    return UUID(body["user_id"]), {"Authorization": f"Bearer {body['token']}"}


async def practice(engine: AsyncEngine, user_id: UUID, when: datetime, right: list[bool]) -> UUID:
    session_id, round_id = uuid4(), uuid4()
    async with engine.begin() as conn:
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
                game_id="quick_draw",
                level=0.4,
                status="completed",
                started_at=when,
                scored_at=when,
            )
        )
        await conn.execute(
            t.trials.insert(),
            [
                {
                    "trial_id": uuid4(),
                    "user_id": user_id,
                    "session_id": session_id,
                    "round_id": round_id,
                    "game_id": "quick_draw",
                    "level": 0.4,
                    "trial_index": i,
                    "correct": c,
                    "rt_ms": 400.0,
                    "stimulus": {},
                    "ts": when + timedelta(seconds=i),
                }
                for i, c in enumerate(right)
            ],
        )
        await conn.execute(
            pg_insert(t.history)
            .values(
                user_id=user_id, day=when.date(), dim="processing_speed", mu=0.2, sigma=0.6, n=12
            )
            .on_conflict_do_nothing()  # two practices on one day share one history row
        )
    return session_id


async def test_progress_pills_and_heatmaps(client: httpx.AsyncClient, aengine: AsyncEngine) -> None:
    user_id, headers = await signup(client)
    now = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
    for days_ago in (0, 1, 2, 5):
        await practice(aengine, user_id, now - timedelta(days=days_ago), [True] * 9 + [False] * 3)
    await practice(aengine, user_id, now - timedelta(days=1, hours=3), [True] * 4)  # few answers
    p = (await client.get("/progress", headers=headers)).json()
    assert p["stats"]["streak_days"] == 3 and p["stats"]["rounds_this_week"] == 5
    assert p["stats"]["skills_measured"] == 0  # no dimension_state rows: nothing scored yet
    week = p["by_week"]
    assert week["skills"] == ["processing_speed"] and len(week["weeks"]) == 8
    assert sum(week["rounds"][0]) == 5
    hour = p["by_hour"]
    # 09:00 UTC is 10:00 in Tunis: the "10-14" block, not "6-10".
    row = hour["hours"].index("10-14")
    filled = [a for a in hour["accuracy"][row] if a is not None]
    assert filled and all(a == 0.75 for a in filled)
    early = hour["hours"].index("6-10")  # 06:00 UTC = 07:00 in Tunis, only 4 answers
    assert all(a is None for a in hour["accuracy"][early])
    assert sum(hour["answers"][early]) == 4


async def test_twin_curves_carry_ranges(client: httpx.AsyncClient, aengine: AsyncEngine) -> None:
    user_id, headers = await signup(client)
    await practice(aengine, user_id, datetime.now(UTC), [True] * 10)
    [point] = (await client.get("/twin", headers=headers)).json()["curves"]
    assert point["dim"] == "processing_speed"
    assert point["low"] < point["percent"] < point["high"]


async def test_decisions_and_trace_are_private(
    client: httpx.AsyncClient, aengine: AsyncEngine
) -> None:
    user_id, headers = await signup(client)
    _, other = await signup(client)
    session_id = await practice(aengine, user_id, datetime.now(UTC), [True] * 3)
    async with aengine.begin() as conn:
        await conn.execute(
            t.decisions.insert().values(
                decision_id=uuid4(),
                session_id=session_id,
                user_id=user_id,
                node="plan_next",
                question="Which skill?",
                candidates=[],
                chosen="processing_speed:quick_draw",
                reason="Speed is the skill I'm least sure about.",
            )
        )
        await conn.execute(
            t.traces.insert().values(
                session_id=session_id, user_id=user_id, node="plan_next", event="done", ms=12.5
            )
        )
    mine = (await client.get("/me/decisions", headers=headers)).json()
    assert [d["reason"] for d in mine] == ["Speed is the skill I'm least sure about."]
    assert (await client.get("/me/decisions", headers=other)).json() == []
    trace = (await client.get(f"/sessions/{session_id}/trace", headers=headers)).json()
    assert trace[0]["node"] == "plan_next" and trace[0]["ms"] == 12.5
    assert (await client.get(f"/sessions/{session_id}/trace", headers=other)).status_code == 404


def test_twin_stream_pushes_only_this_users_updates(app: FastAPI, db_url: str) -> None:
    with TestClient(app) as tc:
        me = tc.post("/users", json={"age_confirmed": True}).json()
        other = tc.post("/users", json={"age_confirmed": True}).json()
        with tc.websocket_connect("/twin/stream") as ws:
            ws.send_json({"type": "auth", "token": me["token"]})
            assert ws.receive_json() == {"kind": "ready"}
            with psycopg.connect(libpq_url(db_url), autocommit=True) as conn:
                conn.execute("SELECT pg_notify(%s, %s)", (NOTIFY_CHANNEL, other["user_id"]))
                conn.execute("SELECT pg_notify(%s, %s)", (NOTIFY_CHANNEL, me["user_id"]))
            assert ws.receive_json() == {"kind": "twin_updated"}  # only mine came through
        with tc.websocket_connect("/twin/stream") as ws:
            ws.send_json({"type": "auth", "token": "nope"})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
