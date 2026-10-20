"""Database URLs and engines. SQLAlchemy 2.1 Core on psycopg 3 (docs/plan/04)."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.config import get_settings


def sync_url(database_url: str | None = None) -> str:
    """SQLAlchemy URL for the psycopg 3 driver (sync and async share it)."""
    url = make_url(database_url or get_settings().database_url)
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def libpq_url(database_url: str | None = None) -> str:
    """Plain libpq URL, for psycopg and the LangGraph checkpointer."""
    url = make_url(database_url or get_settings().database_url)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@lru_cache
def get_engine() -> Engine:
    return create_engine(sync_url(), pool_pre_ping=True)


@lru_cache
def get_async_engine() -> AsyncEngine:
    return create_async_engine(sync_url(), pool_pre_ping=True, pool_size=10, max_overflow=10)
