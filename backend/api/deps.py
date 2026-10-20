"""Shared FastAPI dependencies: database access and the current user."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from backend.db.engine import get_async_engine
from backend.db.twin_store import user_for_token
from backend.registry.loader import load_registry
from backend.registry.models import Registry


def engine_dep() -> AsyncEngine:
    return get_async_engine()


def registry_dep() -> Registry:
    return load_registry()


async def conn_dep(
    engine: Annotated[AsyncEngine, Depends(engine_dep)],
) -> AsyncIterator[AsyncConnection]:
    async with engine.begin() as conn:
        yield conn


async def current_user(
    engine: Annotated[AsyncEngine, Depends(engine_dep)],
    authorization: Annotated[str | None, Header()] = None,
) -> UUID:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    async with engine.begin() as conn:
        user_id = await user_for_token(conn, authorization.split(" ", 1)[1].strip())
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown token")
    return user_id


Engine = Annotated[AsyncEngine, Depends(engine_dep)]
Conn = Annotated[AsyncConnection, Depends(conn_dep)]
CurrentUser = Annotated[UUID, Depends(current_user)]
RegistryDep = Annotated[Registry, Depends(registry_dep)]
