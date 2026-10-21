import base64
import os
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.agent.context import Services
from backend.agent.graph import checkpointer, compile_graph
from backend.agent.runner import SessionRunner
from backend.config import Settings, get_settings
from backend.db import tables as t
from backend.db.engine import libpq_url, sync_url
from backend.db.twin_store import create_user
from backend.llm.factory import LlmFactory
from backend.llm.stub import Responder
from backend.registry.loader import load_registry

MASTER_KEY = base64.b64encode(os.urandom(32)).decode()


def test_settings(**overrides: Any) -> Settings:
    from pydantic import SecretStr

    base = get_settings().model_dump()
    base.update(
        {"master_key": SecretStr(MASTER_KEY), "ollama_url": "http://127.0.0.1:9", **overrides}
    )
    return Settings(**base)


@pytest.fixture
async def aengine(db_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(sync_url(db_url))
    yield engine
    await engine.dispose()


RunnerFactory = Callable[..., Any]


@pytest.fixture
async def make_runner(db_url: str, aengine: AsyncEngine) -> AsyncIterator[RunnerFactory]:
    pools: list[AsyncConnectionPool[Any]] = []

    async def build(
        responder: Responder | None = None, base_overrides: dict[str, str] | None = None
    ) -> SessionRunner:
        pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
            libpq_url(db_url),
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await pool.open()
        pools.append(pool)
        registry = load_registry()
        settings = test_settings()
        llm = LlmFactory(
            registry, settings, aengine, stub_responder=responder, base_overrides=base_overrides
        )
        services = Services(engine=aengine, registry=registry, llm=llm)
        return SessionRunner(compile_graph(checkpointer(pool)), services, settings.local_model)

    yield build
    for pool in pools:
        await pool.close()


async def new_user(engine: AsyncEngine, mode: str = "stub", persona: str = "zitouna") -> UUID:
    async with engine.begin() as conn:
        user_id, _ = await create_user(conn, persona=persona)
        await conn.execute(
            t.llm_selection.insert().values(
                user_id=user_id, mode=mode, provider="stub", model="stub"
            )
        )
    return user_id
