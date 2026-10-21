"""API tests for /llm (UW22 basics) and /sessions, including the WebSocket through the real app
lifespan."""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.websockets import WebSocketDisconnect

from backend.agent.context import Services
from backend.agent.graph import checkpointer, compile_graph
from backend.agent.runner import SessionRunner
from backend.api.deps import engine_dep
from backend.api.main import create_app
from backend.config import get_settings
from backend.db import tables as t
from backend.db.engine import get_async_engine, libpq_url, sync_url
from backend.llm.factory import LlmFactory
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import MASTER_KEY, test_settings
from tests.backend.llm.fake_provider import FakeProvider, fake_provider

GEMINI_KEY = "AIzaSyFakeFakeFakeFakeFakeFakeA91F"


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    with fake_provider() as server:
        yield server


@pytest.fixture
async def client(
    aengine: AsyncEngine, fake: FakeProvider, db_url: str
) -> AsyncIterator[httpx.AsyncClient]:
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    registry = load_registry()
    settings = test_settings()
    overrides = {"gemini": fake.base + "/v1beta", "openai": fake.base + "/v1"}
    llm = LlmFactory(registry, settings, aengine, base_overrides=overrides)
    services = Services(engine=aengine, registry=registry, llm=llm)
    pool = AsyncConnectionPool(
        libpq_url(db_url),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    app: FastAPI = create_app(with_lifespan=False)
    app.state.services = services
    app.state.runner = SessionRunner(
        compile_graph(checkpointer(pool)), services, settings.local_model
    )
    app.dependency_overrides[engine_dep] = lambda: aengine
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await pool.close()


async def _auth(client: httpx.AsyncClient) -> dict[str, str]:
    created = (await client.post("/users")).json()
    return {"Authorization": f"Bearer {created['token']}"}


async def test_saving_a_key_shows_only_last4_and_selects_the_provider(
    client: httpx.AsyncClient, fake: FakeProvider
) -> None:
    headers = await _auth(client)
    saved = await client.put(
        "/llm/credentials/gemini", json={"api_key": GEMINI_KEY}, headers=headers
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["credential"] == {"provider": "gemini", "key_last4": "A91F", "status": "ok"}
    assert body["models"] == ["m"] and GEMINI_KEY not in saved.text
    overview = (await client.get("/llm/providers", headers=headers)).json()
    assert (
        overview["selection"]["mode"] == "hosted" and overview["selection"]["provider"] == "gemini"
    )
    assert GEMINI_KEY not in str(overview) and len(overview["providers"]) == 9
    assert fake.requests[-1].headers["x-goog-api-key"] == GEMINI_KEY  # header, never the URL

    removed = await client.delete("/llm/credentials/gemini", headers=headers)
    assert removed.status_code == 204
    overview = (await client.get("/llm/providers", headers=headers)).json()
    assert overview["selection"]["mode"] == "local" and overview["credentials"] == []


async def test_a_rejected_key_is_not_saved(client: httpx.AsyncClient, fake: FakeProvider) -> None:
    headers = await _auth(client)
    fake.reject_keys = True
    saved = await client.put(
        "/llm/credentials/openai", json={"api_key": "sk-wrongwrongwrong"}, headers=headers
    )
    assert saved.status_code == 400 and "didn't work" in saved.json()["detail"]
    overview = (await client.get("/llm/providers", headers=headers)).json()
    assert overview["credentials"] == [] and overview["selection"]["mode"] == "local"


async def test_hosted_selection_needs_a_key(client: httpx.AsyncClient) -> None:
    headers = await _auth(client)
    body = {"mode": "hosted", "provider": "anthropic", "model": "claude-opus-5-5"}
    assert (await client.put("/llm/selection", json=body, headers=headers)).status_code == 400


def _trials(spec: dict[str, Any], session_id: str, correct: list[bool]) -> list[dict[str, Any]]:
    start = datetime.now(UTC)
    return [
        {"trial_id": str(uuid4()), "round_id": spec["round_id"], "session_id": session_id,
         "game_id": spec["game_id"], "level": spec["level"], "trial_index": i, "stimulus": {},
         "correct": c, "rt_ms": 550.0, "ts": (start + timedelta(seconds=3 * i)).isoformat()}
        for i, c in enumerate(correct)
    ]  # fmt: skip


def _result(spec: dict[str, Any], n: int) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {"round_id": spec["round_id"], "game_id": spec["game_id"], "status": "completed",
            "trial_count": n, "final_level": spec["level"], "started_at": now.isoformat(),
            "ended_at": (now + timedelta(minutes=1)).isoformat()}  # fmt: skip


async def test_session_endpoints_play_a_round(
    client: httpx.AsyncClient, aengine: AsyncEngine
) -> None:
    headers = await _auth(client)
    started = (await client.post("/sessions", json={"trigger": "ui"}, headers=headers)).json()
    session_id = started["session_id"]
    [interrupt] = [e for e in started["events"] if e["kind"] == "interrupt"]
    spec = interrupt["payload"]["spec"]
    pending = (await client.get(f"/sessions/{session_id}/pending", headers=headers)).json()
    assert pending["pending"]["payload"]["spec"]["round_id"] == spec["round_id"]
    ok = await client.post(
        "/events", json={"trials": _trials(spec, session_id, [True] * 8)}, headers=headers
    )
    assert ok.json()["accepted"] == 8
    resumed = await client.post(
        f"/sessions/{session_id}/resume", json={"value": _result(spec, 8)}, headers=headers
    )
    kinds = [e["kind"] for e in resumed.json()["events"]]
    assert "say" in kinds and "interrupt" in kinds  # coached, then paused for the next round
    twin = (await client.get("/twin", headers=headers)).json()
    assert twin["dims"]


def test_websocket_through_the_real_lifespan(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The browser path: real lifespan, auth frame, start, trials over HTTP, resume over WS."""
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("NAJMA_MASTER_KEY", MASTER_KEY)
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()
    get_async_engine.cache_clear()
    try:
        with TestClient(create_app()) as tc:
            created = tc.post("/users").json()
            token, user_id = created["token"], UUID(created["user_id"])
            engine = create_engine(sync_url(db_url))
            with engine.begin() as conn:  # deterministic coach: the stub model
                conn.execute(t.llm_selection.insert().values(
                    user_id=user_id, mode="stub", provider="stub", model="stub"))  # fmt: skip
            engine.dispose()
            headers = {"Authorization": f"Bearer {token}"}
            session = tc.post("/sessions", json={"trigger": "ui"}, headers=headers).json()
            session_id = session["session_id"]

            with tc.websocket_connect(f"/sessions/{session_id}/stream") as ws:
                ws.send_json({"type": "auth", "token": token})
                waiting = ws.receive_json()  # the session is paused at play
                assert waiting["kind"] == "interrupt"
                spec = waiting["payload"]["spec"]
                tc.post(
                    "/events",
                    json={"trials": _trials(spec, session_id, [True] * 9)},
                    headers=headers,
                )
                ws.send_json({"type": "resume", "value": _result(spec, 9)})
                events = []
                while True:
                    event = ws.receive_json()
                    events.append(event)
                    if event["kind"] == "done":
                        break
            kinds = {e["kind"] for e in events}
            assert {"node", "say", "decision", "interrupt"} <= kinds

            with tc.websocket_connect(f"/sessions/{session_id}/stream") as ws:
                ws.send_json({"type": "auth", "token": "wrong"})
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
    finally:
        get_settings.cache_clear()
        get_async_engine.cache_clear()


async def test_affect_labels_go_to_the_event_log(
    client: httpx.AsyncClient, aengine: AsyncEngine
) -> None:
    headers = await _auth(client)
    started = (await client.post("/sessions", json={"trigger": "ui"}, headers=headers)).json()
    session_id = started["session_id"]
    body = {"session_id": session_id, "kind": "mood", "value": "tough"}
    assert (await client.post("/affect/labels", json=body, headers=headers)).status_code == 204
    bad = {**body, "value": "furious"}
    assert (await client.post("/affect/labels", json=bad, headers=headers)).status_code == 422
    other = await _auth(client)  # someone else's session
    assert (await client.post("/affect/labels", json=body, headers=other)).status_code == 404
    async with aengine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    select(t.events.c.payload).where(
                        t.events.c.session_id == UUID(session_id),
                        t.events.c.type == "affect.labelled",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [r["value"] for r in rows] == ["tough"]
