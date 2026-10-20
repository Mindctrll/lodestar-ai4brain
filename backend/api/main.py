"""FastAPI entry point. `create_app` wires the routes; the lifespan opens the database pools, the
LangGraph Postgres checkpointer and the LLM factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.agent.context import Services
from backend.agent.graph import checkpointer, compile_graph
from backend.agent.runner import SessionRunner
from backend.api import llm, registry, sessions, twin
from backend.api.llm import llm_factory_dep
from backend.config import get_settings
from backend.db.engine import get_async_engine, libpq_url
from backend.llm import redaction
from backend.llm.factory import LlmFactory
from backend.registry.loader import load_registry


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
    services = Services(engine=engine, registry=reg, llm=LlmFactory(reg, settings, engine))
    app.state.services = services
    app.state.runner = SessionRunner(
        compile_graph(checkpointer(pool)), services, settings.local_model
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
    app.dependency_overrides[llm_factory_dep] = lambda: app.state.services.llm

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
