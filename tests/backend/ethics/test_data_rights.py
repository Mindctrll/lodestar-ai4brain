"""WP2.8 "Done when": deleting a user leaves zero rows, points, notes and checkpoints; turning a
switch off stops that processing. Also the 18+ gate, consent events, export without keys,
memory edits (UW14), de-identified text for cloud AI, and the retention job."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.messages import HumanMessage
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.context import Services
from backend.agent.graph import checkpointer, compile_graph
from backend.agent.runner import SessionRunner
from backend.api.deps import engine_dep
from backend.api.main import create_app
from backend.contracts.llm import LlmSelection
from backend.db import tables as t
from backend.db.engine import libpq_url
from backend.db.llm_store import save_credential, set_selection
from backend.db.twin_store import rebuild_twin
from backend.ethics.data_rights import USER_TABLES
from backend.ethics.retention import run_retention
from backend.llm.factory import LlmFactory
from backend.llm.vault import Vault
from backend.memory.langgraph_store import QdrantStore
from backend.memory.notes import Notes
from backend.memory.store import MemoryStore
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import MASTER_KEY, grant, new_user, test_settings
from tests.backend.agent.test_graph import collect, interrupt_of, play
from tests.backend.agent.test_policy import returning_user
from tests.backend.llm.fake_provider import FakeProvider, fake_provider

REGISTRY = load_registry()


@pytest.fixture
def fake() -> AsyncIterator[FakeProvider]:
    with fake_provider() as server:
        yield server  # type: ignore[misc]


@pytest.fixture
async def app(
    db_url: str, aengine: AsyncEngine, memory: MemoryStore, tmp_path: Path, fake: FakeProvider
) -> AsyncIterator[FastAPI]:
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        libpq_url(db_url),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    settings = test_settings()
    llm = LlmFactory(REGISTRY, settings, aengine, base_overrides={"openai": fake.base + "/v1"})
    services = Services(
        engine=aengine, registry=REGISTRY, llm=llm, memory=memory, notes=Notes(tmp_path)
    )
    application = create_app(with_lifespan=False)
    application.state.services = services
    application.state.runner = SessionRunner(
        compile_graph(checkpointer(pool), QdrantStore(memory)), services, settings.local_model
    )
    from backend.api.llm import llm_factory_dep

    application.dependency_overrides[engine_dep] = lambda: aengine
    application.dependency_overrides[llm_factory_dep] = lambda: llm
    yield application
    await pool.close()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def signup(client: httpx.AsyncClient, **consent: bool) -> tuple[UUID, dict[str, str]]:
    created = await client.post("/users", json={"age_confirmed": True, "consent": consent})
    assert created.status_code == 201, created.text
    body = created.json()
    return UUID(body["user_id"]), {"Authorization": f"Bearer {body['token']}"}


# Age gate and consent -------------------------------------------------------------------------


async def test_age_gate_and_core_consent(client: httpx.AsyncClient, aengine: AsyncEngine) -> None:
    async with aengine.connect() as conn:
        before = (await conn.execute(select(func.count()).select_from(t.users))).scalar_one()
    under = await client.post("/users", json={"age_confirmed": False})
    assert under.status_code == 403 and "18" in under.json()["detail"]
    no_core = await client.post("/users", json={"age_confirmed": True, "consent": {"core": False}})
    assert no_core.status_code == 422
    async with aengine.connect() as conn:
        after = (await conn.execute(select(func.count()).select_from(t.users))).scalar_one()
    assert after == before  # nobody was created


async def test_consent_switches_are_logged_with_the_notice_version(
    client: httpx.AsyncClient, aengine: AsyncEngine
) -> None:
    user_id, headers = await signup(client, microphone=True)
    view = (await client.get("/consent", headers=headers)).json()
    state = {s["id"]: s["granted"] for s in view["switches"]}
    assert state == {
        "core": True, "cloud_ai": False, "microphone": True, "camera": False,
        "voice_tone": False, "deliberate_mistakes": True, "research_export": False,
    }  # fmt: skip
    assert (
        await client.put("/consent/core", json={"granted": False}, headers=headers)
    ).status_code == 409
    changed = await client.put("/consent/microphone", json={"granted": False}, headers=headers)
    assert {s["id"]: s["granted"] for s in changed.json()["switches"]}["microphone"] is False
    async with aengine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    select(t.events.c.payload)
                    .where(t.events.c.user_id == user_id, t.events.c.type == "consent.changed")
                    .order_by(t.events.c.ts)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 8  # seven at sign-up, one change
    assert rows[-1] == {
        "switch": "microphone",
        "granted": False,
        "notice_version": REGISTRY.consent.version,
    }


# Switches stop processing ---------------------------------------------------------------------


async def test_turning_cloud_ai_off_stops_it_at_once(
    client: httpx.AsyncClient, app: FastAPI, aengine: AsyncEngine, fake: FakeProvider
) -> None:
    user_id, headers = await signup(client, cloud_ai=True)
    saved = await client.put(
        "/llm/credentials/openai", json={"api_key": "sk-test-1234567890"}, headers=headers
    )
    assert saved.status_code == 200, saved.text
    runner: SessionRunner = app.state.runner
    assert (await runner.context_for(user_id, uuid4())).llm.mode == "hosted"
    off = await client.put("/consent/cloud_ai", json={"granted": False}, headers=headers)
    assert off.status_code == 200
    overview = (await client.get("/llm/providers", headers=headers)).json()
    assert overview["selection"]["mode"] == "local"
    # Even if a hosted selection were left behind, a run never uses it without the switch.
    async with aengine.begin() as conn:
        await set_selection(
            conn, user_id, LlmSelection(mode="hosted", provider="openai", model="m")
        )
    assert (await runner.context_for(user_id, uuid4())).llm.mode == "local"
    calls = len(fake.requests)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    await play(runner, aengine, user_id, session_id, spec, [True] * 8)
    assert len(fake.requests) == calls  # nothing went to the cloud provider


async def test_planted_mistakes_switch_keeps_spot_the_mistake_out(
    app: FastAPI, aengine: AsyncEngine
) -> None:
    runner: SessionRunner = app.state.runner
    user_id = await returning_user(aengine)
    await grant(aengine, user_id, "deliberate_mistakes", granted=False)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id, message="play Spot the AI's Mistake")
    spec = interrupt_of(events)
    assert spec["game_id"] != "spot_the_mistake"
    [plan] = [e for e in events if e["kind"] == "decision" and e["node"] == "plan_next"]
    assert "switched off in your privacy settings" in plan["reason"]


# De-identified text for cloud AI --------------------------------------------------------------


async def test_cloud_ai_gets_deidentified_text(aengine: AsyncEngine, fake: FakeProvider) -> None:
    llm = LlmFactory(
        REGISTRY, test_settings(), aengine, base_overrides={"openai": fake.base + "/v1"}
    )
    user_id = await new_user(aengine)
    async with aengine.begin() as conn:
        await conn.execute(
            update(t.users).where(t.users.c.user_id == user_id).values(display_name="Amira")
        )
        await save_credential(
            conn,
            user_id,
            "openai",
            Vault(MASTER_KEY).seal(user_id, "openai", "sk-x-12345678"),
            "ok",
        )
    said = (
        "My name is Amira, write to amira.b@insat.tn or +216 22 333 444. "
        f"Id {user_id}. Amira likes maths."
    )
    hosted = LlmSelection(mode="hosted", provider="openai", model="m")
    await llm.generate(user_id, hosted, [HumanMessage(said)])
    sent = json.dumps(fake.requests[-1].body)
    for secret in ("Amira", "amira.b@insat.tn", "333 444", str(user_id)):
        assert secret not in sent, secret
    assert "likes maths" in sent  # the meaning survives


# Export, memory edits, delete (UW14) ----------------------------------------------------------


async def _lived_in(
    client: httpx.AsyncClient, app: FastAPI, aengine: AsyncEngine
) -> tuple[UUID, dict[str, str]]:
    """A user with sessions, rounds, events, memories, notes, a goal and a saved key."""
    user_id, headers = await signup(client, cloud_ai=True)
    runner: SessionRunner = app.state.runner
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id, message="I slept like 4 hours.")
    assert any(e["kind"] == "interrupt" for e in events)
    await collect(runner, user_id, session_id, resume={"confirmed": True})
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    while True:
        events = await play(runner, aengine, user_id, session_id, spec, [True] * 8 + [False] * 2)
        if not any(e["kind"] == "interrupt" for e in events):
            break
        spec = interrupt_of(events)
    async with aengine.begin() as conn:
        sealed = Vault(MASTER_KEY).seal(user_id, "openai", "sk-canary-0123456789abcdef")
        await save_credential(conn, user_id, "openai", sealed, "ok")
    return user_id, headers


async def test_export_has_everything_and_never_a_key(
    client: httpx.AsyncClient, app: FastAPI, aengine: AsyncEngine
) -> None:
    user_id, headers = await _lived_in(client, app, aengine)
    response = await client.get("/me/export", headers=headers)
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    data = response.json()
    assert "sk-canary" not in response.text and "key_ciphertext" not in response.text
    assert "token_hash" not in response.text
    assert data["tables"]["twin.rounds"] and data["tables"]["twin.events"]
    assert data["tables"]["app.llm_credentials"][0]["key_last4"] == "cdef"
    assert data["memories"]["episodic"] and "core.md" in data["notes"]
    async with aengine.connect() as conn:
        exported = (
            await conn.execute(
                select(func.count())
                .select_from(t.events)
                .where(t.events.c.user_id == user_id, t.events.c.type == "data.exported")
            )
        ).scalar_one()
    assert exported == 1


async def test_memory_lines_can_be_seen_and_deleted(
    client: httpx.AsyncClient, app: FastAPI, aengine: AsyncEngine, memory: MemoryStore
) -> None:
    user_id, headers = await _lived_in(client, app, aengine)
    services: Services = app.state.services
    assert services.notes is not None
    services.notes.write_core(
        user_id, ["Usually plays in the evening", "Prefers the Zitouna coach"]
    )
    point_id = await memory.write(
        user_id, "Usually plays in the evening", collection="facts", kind="preference",
        importance=0.8,
    )  # fmt: skip
    mine = (await client.get("/me/data", headers=headers)).json()
    assert "Usually plays in the evening" in mine["core"] and mine["life_context"]
    assert any(m["id"] == str(point_id) for m in mine["memories"])
    gone = await client.post(
        "/me/core/forget", json={"line": "Usually plays in the evening"}, headers=headers
    )
    assert gone.status_code == 204
    assert services.notes.read_core(user_id) == ["Prefers the Zitouna coach"]
    assert await memory.get(user_id, "facts", point_id) is None  # gone from Qdrant too
    other_id, other = await signup(client)
    episodic = (await client.get("/me/data", headers=headers)).json()["memories"]
    target = next(m for m in episodic if m["collection"] == "episodic")
    stranger = await client.delete(f"/me/memories/episodic/{target['id']}", headers=other)
    assert stranger.status_code == 404  # another user can't touch it
    own = await client.delete(f"/me/memories/episodic/{target['id']}", headers=headers)
    assert own.status_code == 204
    assert other_id != user_id


async def test_delete_leaves_nothing_behind(
    client: httpx.AsyncClient,
    app: FastAPI,
    aengine: AsyncEngine,
    memory: MemoryStore,
    tmp_path: Path,
) -> None:
    user_id, headers = await _lived_in(client, app, aengine)
    async with aengine.connect() as conn:
        sessions = [
            str(s)
            for s in (
                await conn.execute(
                    select(t.sessions.c.session_id).where(t.sessions.c.user_id == user_id)
                )
            ).scalars()
        ]
        before = {
            name: (
                await conn.execute(
                    select(func.count()).select_from(table).where(table.c.user_id == user_id)
                )
            ).scalar_one()
            for name, table in (
                ("events", t.events),
                ("rounds", t.rounds),
                ("sessions", t.sessions),
            )
        }
    points = len(await memory.points(user_id, "episodic")) + len(
        await memory.points(user_id, "facts")
    )
    assert points > 0 and before["rounds"] > 0 and sessions

    receipt = await client.delete("/me", headers=headers)
    assert receipt.status_code == 200, receipt.text
    counts = receipt.json()["counts"]
    assert {k: counts[k] for k in before} == before and counts["memories"] == points
    assert receipt.json()["message"].startswith("Deleted ")

    async with aengine.connect() as conn:
        # Every table with a user_id column, found from the database itself.
        found = await conn.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.columns "
                "WHERE column_name = 'user_id' AND table_schema IN ('app', 'twin', 'agent') "
                "AND table_name NOT LIKE 'events\\_%'"
            )
        )
        for schema, table in found:
            n = (
                await conn.execute(
                    text(f"SELECT count(*) FROM {schema}.{table} WHERE user_id = :u"),
                    {"u": user_id},
                )
            ).scalar_one()
            assert n == 0, f"{schema}.{table}"
        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            n = (
                await conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE thread_id = ANY(:s)"), {"s": sessions}
                )
            ).scalar_one()
            assert n == 0, table
        receipts = (await conn.execute(select(t.deletion_receipts.c.counts))).scalars().all()
    assert counts in receipts
    for collection in ("episodic", "facts"):
        assert await memory.points(user_id, collection) == []
    assert not (tmp_path / str(user_id)).exists()
    assert (await client.get("/consent", headers=headers)).status_code == 401  # token gone too


def test_user_tables_cover_the_schema() -> None:
    """USER_TABLES (used by export and the receipt) must list every table with a user_id."""
    with_user = {
        f"{tbl.schema}.{tbl.name}" for tbl in t.metadata.tables.values() if "user_id" in tbl.c
    }
    assert with_user == {f"{tbl.schema}.{tbl.name}" for tbl in USER_TABLES}


# Retention ------------------------------------------------------------------------------------


async def test_retention_drops_old_data_and_keeps_the_profile_rebuildable(
    app: FastAPI, aengine: AsyncEngine
) -> None:
    runner: SessionRunner = app.state.runner
    user_id = await new_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    await play(runner, aengine, user_id, session_id, spec, [True] * 8)
    now = datetime.now(UTC)
    old = now - timedelta(days=400)
    async with aengine.begin() as conn:
        await conn.execute(text("SELECT twin.ensure_event_partitions(15, 0)"))
        await conn.execute(
            text(
                "INSERT INTO twin.events (user_id, ts, type, payload) VALUES "
                '(:u, :ts, \'session.started\', \'{"trigger": "ui", "persona": "zitouna"}\')'
            ),
            {"u": user_id, "ts": old},
        )
        await conn.execute(
            update(t.sessions)
            .where(t.sessions.c.session_id == session_id)
            .values(started_at=now - timedelta(days=40))
        )
        await conn.execute(
            update(t.traces)
            .where(t.traces.c.session_id == session_id)
            .values(ts=now - timedelta(days=40))
        )
        state_before = {
            r.dim: (round(r.mu, 9), round(r.sigma, 9))
            for r in await conn.execute(
                select(t.dimension_state).where(t.dimension_state.c.user_id == user_id)
            )
        }
    counts = await run_retention(aengine, now)
    assert counts["partitions_dropped"] >= 1 and counts["snapshots"] >= 1
    assert counts["traces"] > 0 and counts["checkpoints"] > 0
    async with aengine.connect() as conn:
        old_left = (
            await conn.execute(
                select(func.count())
                .select_from(t.events)
                .where(t.events.c.ts < now - timedelta(days=366))
            )
        ).scalar_one()
        assert old_left == 0
        left = (
            await conn.execute(
                text("SELECT count(*) FROM checkpoints WHERE thread_id = :s"),
                {"s": str(session_id)},
            )
        ).scalar_one()
        assert left == 0
    await rebuild_twin(aengine, user_id)
    async with aengine.connect() as conn:
        state_after = {
            r.dim: (round(r.mu, 9), round(r.sigma, 9))
            for r in await conn.execute(
                select(t.dimension_state).where(t.dimension_state.c.user_id == user_id)
            )
        }
    assert state_after == state_before
