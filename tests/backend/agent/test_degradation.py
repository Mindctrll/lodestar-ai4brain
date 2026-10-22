"""The degradation ladder (WP4.1, docs/plan/03 and 15): a full session completes with the LLM
down, with Qdrant down and across a Postgres reconnect; a refresh mid-game resumes the round and
scores it once, counting the replay and not the unfinished attempt."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from qdrant_client import AsyncQdrantClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.agent.runner import SessionRunner
from backend.contracts.trial import TrialEvent
from backend.db import tables as t
from backend.db.engine import libpq_url, sync_url
from backend.db.twin_store import record_trials
from backend.memory.embeddings import Embedder
from backend.memory.notes import Notes
from backend.memory.store import MemoryStore
from tests.backend.agent.conftest import RunnerFactory, new_user
from tests.backend.agent.test_graph import collect, interrupt_of, play

DEAD = "http://127.0.0.1:9"  # nothing listens here


async def full_session(
    runner: SessionRunner, engine: AsyncEngine, user_id: UUID
) -> list[dict[str, Any]]:
    """Play every round the agent offers until the session ends; return every event."""
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id)
    seen = list(events)
    while any(e["kind"] == "interrupt" for e in events):
        spec = interrupt_of(events)
        events = await play(runner, engine, user_id, session_id, spec, [True] * 9 + [False] * 3)
        seen += events
    async with engine.connect() as conn:
        status = (await conn.execute(
            select(t.sessions.c.status).where(t.sessions.c.session_id == session_id)
        )).scalar_one()  # fmt: skip
    assert status == "ended" and seen[-1] == {"kind": "done", "waiting": False}
    assert any(e["kind"] == "say" for e in seen)
    return seen


async def play_trials_only(
    engine: AsyncEngine, user_id: UUID, session_id: UUID, spec: dict[str, Any], results: list[bool]
) -> None:
    start = datetime.now(UTC) - timedelta(minutes=5)
    trials = [
        TrialEvent(
            trial_id=uuid4(), round_id=UUID(spec["round_id"]), session_id=session_id,
            game_id=spec["game_id"], level=spec["level"], trial_index=i, stimulus={},
            correct=c, rt_ms=600.0, ts=start + timedelta(seconds=4 * i),
        )
        for i, c in enumerate(results)
    ]  # fmt: skip
    async with engine.begin() as conn:
        await record_trials(conn, user_id, trials)


async def test_llm_down_completes_a_full_session(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    def broken(messages: Any) -> str:
        raise RuntimeError("model down")

    runner = await make_runner(responder=broken)
    events = await full_session(runner, aengine, await new_user(aengine))
    assert any(e["kind"] == "degraded" and e["to"] == "template" for e in events)


async def test_qdrant_down_completes_a_full_session(
    make_runner: RunnerFactory, aengine: AsyncEngine, embedder: Embedder, tmp_path: Path
) -> None:
    client = AsyncQdrantClient(url=DEAD, timeout=1)
    memory = MemoryStore(client, embedder)
    runner = await make_runner(memory=memory, notes=Notes(tmp_path))
    try:
        events = await full_session(runner, aengine, await new_user(aengine))
    finally:
        await client.close()
    hit = {e["what"] for e in events if e["kind"] == "degraded"}
    assert {"recall_memory", "memory"} & hit  # the dead Qdrant was really tried, then skipped


async def test_postgres_reconnect_mid_session(make_runner: RunnerFactory, db_url: str) -> None:
    """Every connection the app holds is dropped while the user plays; the round still scores."""
    name = "lodestar_reconnect_test"
    url = f"{db_url}?application_name={name}"
    engine = create_async_engine(sync_url(url), pool_pre_ping=True)  # as get_async_engine()
    try:
        runner = await make_runner(url=url, engine=engine)
        user_id = await new_user(engine)
        session_id = await runner.create_session(user_id, "ui")
        spec = interrupt_of(await collect(runner, user_id, session_id))
        with psycopg.connect(libpq_url(db_url), autocommit=True) as admin:
            dropped = admin.execute(
                "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity"
                " WHERE application_name = %s",
                (name,),
            ).fetchone()
        assert dropped is not None and dropped[0] >= 2  # the app's pool and the checkpointer's
        events = await play(runner, engine, user_id, session_id, spec, [True] * 10)
        assert any(e["kind"] == "say" for e in events)
    finally:
        await engine.dispose()


async def test_refresh_mid_game_resumes_and_counts_the_replay_once(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await new_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    # Half the round, all wrong, reaches /events; then the page reloads before the result.
    await play_trials_only(aengine, user_id, session_id, spec, [False] * 5)
    pending = await runner.pending(user_id, session_id)
    assert pending is not None and pending["payload"]["spec"]["round_id"] == spec["round_id"]
    # Resume replays the same round from the start (same seed, same trial indices).
    events = await play(runner, aengine, user_id, session_id, spec, [True] * 10)
    assert any(e["kind"] == "say" for e in events)
    async with aengine.connect() as conn:
        payload = (await conn.execute(text(
            "SELECT payload FROM twin.events WHERE user_id = :u AND type = 'twin.updated'"
        ), {"u": user_id})).scalar_one()  # fmt: skip
    # 10 answers counted, not 15: the replay replaces the unfinished attempt.
    assert max(c["n_after"] for c in payload["changes"]) == 10
