"""FastAPI entry point. `create_app` wires the routes; the lifespan opens the database pools, the
LangGraph Postgres checkpointer and the LLM factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from qdrant_client import AsyncQdrantClient

from backend.agent.context import Services
from backend.agent.graph import checkpointer, compile_graph
from backend.agent.runner import SessionRunner
from backend.api import affect, goals, llm, me, progress, registry, sessions, twin, voice
from backend.api.llm import llm_factory_dep
from backend.config import Settings, get_settings
from backend.db.engine import get_async_engine, libpq_url
from backend.generation.pipeline import ContentService
from backend.llm import redaction
from backend.llm.factory import LlmFactory
from backend.memory.embeddings import Embedder
from backend.memory.langgraph_store import QdrantStore
from backend.memory.notes import Notes
from backend.memory.store import MemoryStore
from backend.ml.serve import GrowthForecaster
from backend.registry.loader import load_knowledge_items, load_registry

log = logging.getLogger(__name__)


async def _memory(settings: Settings) -> tuple[MemoryStore | None, QdrantStore | None]:
    """Qdrant-backed memory, or (None, None) if Qdrant is down: sessions continue without it."""
    try:
        memory = MemoryStore(AsyncQdrantClient(url=settings.qdrant_url, timeout=5), Embedder())
        await memory.ensure_collections()
        await memory.load_knowledge(load_knowledge_items())
    except Exception:
        log.warning("Qdrant unavailable; memory is off for this run", exc_info=True)
        return None, None
    return memory, QdrantStore(memory)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redaction.install()
    settings = get_settings()
    engine = get_async_engine()
    reg = load_registry()
    pool = AsyncConnectionPool(
        libpq_url(),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    memory, store = await _memory(settings)
    llm = LlmFactory(reg, settings, engine)
    services = Services(
        engine=engine,
        registry=reg,
        llm=llm,
        memory=memory,
        notes=Notes(settings.memory_dir),
        content=ContentService(engine, llm, memory),
        forecaster=await GrowthForecaster.load_active(engine),
    )
    app.state.services = services
    app.state.runner = SessionRunner(
        compile_graph(checkpointer(pool), store), services, settings.local_model
    )
    try:
        yield
    finally:
        await pool.close()
        await engine.dispose()


def create_app(*, with_lifespan: bool = True) -> FastAPI:
    app = FastAPI(title="Najma API", version="0.1.0", lifespan=lifespan if with_lifespan else None)
    app.include_router(registry.router)
    app.include_router(twin.router)
    app.include_router(llm.router)
    app.include_router(sessions.router)
    app.include_router(affect.router)
    app.include_router(goals.router)
    app.include_router(me.router)
    app.include_router(progress.router)
    app.include_router(voice.router)
    app.dependency_overrides[llm_factory_dep] = lambda: app.state.services.llm

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
