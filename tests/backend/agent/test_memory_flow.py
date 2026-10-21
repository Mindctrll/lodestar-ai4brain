"""The agent with real memory: a self-statement is remembered, and the session end writes the
journal, core.md and Qdrant points (UW9 underneath, docs/plan/04 consolidation)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.context import Services
from backend.agent.graph import checkpointer, compile_graph
from backend.agent.runner import SessionRunner
from backend.db.engine import libpq_url
from backend.llm.factory import LlmFactory
from backend.memory.langgraph_store import QdrantStore
from backend.memory.notes import Notes
from backend.memory.store import MemoryStore
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import new_user, test_settings
from tests.backend.agent.test_graph import collect, interrupt_of, play


@pytest.fixture
async def runner_with_memory(
    db_url: str, aengine: AsyncEngine, memory: MemoryStore, tmp_path: Path
) -> AsyncIterator[tuple[SessionRunner, MemoryStore, Notes]]:
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        libpq_url(db_url),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    registry = load_registry()
    settings = test_settings()
    notes = Notes(tmp_path)
    services = Services(
        engine=aengine, registry=registry, llm=LlmFactory(registry, settings, aengine),
        memory=memory, notes=notes,
    )  # fmt: skip
    graph = compile_graph(checkpointer(pool), QdrantStore(memory))
    yield SessionRunner(graph, services, settings.local_model), memory, notes
    await pool.close()


async def test_session_remembers_and_consolidates(
    runner_with_memory: tuple[SessionRunner, MemoryStore, Notes], aengine: AsyncEngine
) -> None:
    runner, memory, notes = runner_with_memory
    user_id = await new_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    await collect(
        runner, user_id, session_id, message="I have my exams next week, I'm a bit stressed"
    )
    hits = await memory.recall(user_id, "exams next week")
    assert hits and "exams next week" in hits[0].text

    events = await collect(runner, user_id, session_id, message="let's play")
    spec = interrupt_of(events)
    for round_no in range(3):
        events = await play(runner, aengine, user_id, session_id, spec, [True] * 10)
        if round_no < 2:
            spec = interrupt_of(events)
    assert not any(e["kind"] == "degraded" and e["what"] == "memory" for e in events)
    journal = notes.read_journal(user_id, datetime.now(UTC).date()) or ""
    assert "Session on" in journal and "played" in journal
    assert notes.read_core(user_id)[0] == "Prefers the Zitouna coach"
    episodic = await memory.points(user_id, "episodic")
    assert any(p.payload["kind"] == "session_summary" for p in episodic)
    assert uuid.UUID(str(user_id))  # every point belongs to this user only
    assert all(p.payload["user_id"] == str(user_id) for p in episodic)
