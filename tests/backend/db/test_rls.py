"""Row-level security (WP4.1, migration 0007): a per-user connection can't see or write another
user's rows, the app role really is subject to RLS, and admin paths still see everything."""

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.api.deps import conn_dep
from backend.db import tables as t
from backend.db.engine import sync_url
from backend.db.twin_store import create_user, user_scope


@pytest.fixture
async def aengine(db_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(sync_url(db_url))
    yield engine
    await engine.dispose()


async def _user_with_session(engine: AsyncEngine) -> UUID:
    async with engine.begin() as conn:
        user_id, _ = await create_user(conn)
        await conn.execute(t.sessions.insert().values(user_id=user_id, trigger="ui"))
    return user_id


async def test_user_a_cannot_read_or_write_user_b(aengine: AsyncEngine) -> None:
    a, b = await _user_with_session(aengine), await _user_with_session(aengine)
    async with aengine.begin() as conn:
        await user_scope(conn, a)
        assert (await conn.execute(text("SELECT current_user"))).scalar_one() == "lodestar_app"
        users = (await conn.execute(select(t.users.c.user_id))).scalars().all()
        assert users == [a]  # no WHERE clause, still only A
        theirs = select(func.count()).select_from(t.sessions).where(t.sessions.c.user_id == b)
        assert (await conn.execute(theirs)).scalar_one() == 0
        deleted = await conn.execute(t.sessions.delete().where(t.sessions.c.user_id == b))
        assert deleted.rowcount == 0
    with pytest.raises(DBAPIError, match="row-level security"):
        async with aengine.begin() as conn:
            await user_scope(conn, a)
            await conn.execute(t.sessions.insert().values(user_id=b, trigger="ui"))
    with pytest.raises(DBAPIError, match="permission denied"):  # the log stays append-only
        async with aengine.begin() as conn:
            await user_scope(conn, a)
            await conn.execute(text("UPDATE twin.events SET type = type"))
    # The admin path (table owner) still sees both, and B's session survived.
    async with aengine.connect() as conn:
        found = select(func.count()).select_from(t.sessions).where(t.sessions.c.user_id.in_([a, b]))
        assert (await conn.execute(found)).scalar_one() == 2


async def test_api_reads_are_scoped_to_the_signed_in_user(aengine: AsyncEngine) -> None:
    a = await _user_with_session(aengine)
    reads = conn_dep(aengine, a)
    conn = await anext(reads)
    try:
        assert (await conn.execute(select(t.users.c.user_id))).scalars().all() == [a]
    finally:
        await reads.aclose()


async def test_every_user_table_is_protected_and_the_app_role_cannot_bypass(
    aengine: AsyncEngine,
) -> None:
    async with aengine.connect() as conn:
        role = (await conn.execute(text(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = 'lodestar_app'"
        ))).scalar_one()  # fmt: skip
        unprotected = (await conn.execute(text("""
            SELECT c.oid::regclass::text FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
            WHERE a.attname = 'user_id' AND c.relkind IN ('r', 'p') AND NOT c.relispartition
              AND c.relnamespace::regnamespace::text IN ('app', 'twin', 'agent')
              AND (NOT c.relrowsecurity OR pg_get_userbyid(c.relowner) = 'lodestar_app')
        """))).scalars().all()  # fmt: skip
    assert role is False and unprotected == []
