"""Consent switches (docs/plan/14). `app.consent` holds the current state; every change is also a
`consent.changed` event with the notice version the user saw."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from backend.contracts.events import ConsentChanged, ConsentPayload
from backend.db import tables as t
from backend.db.twin_store import append_event
from backend.registry.models import ConsentNotice


class RequiredSwitch(ValueError):
    """Core practice data can't be switched off; deleting the data is the way to stop it."""


async def consent_state(
    conn: AsyncConnection, user_id: UUID, notice: ConsentNotice
) -> dict[str, bool]:
    """Every switch: the user's choice, or the notice default if they never chose."""
    rows = await conn.execute(
        select(t.consent.c.switch, t.consent.c.granted).where(t.consent.c.user_id == user_id)
    )
    chosen = {r.switch: bool(r.granted) for r in rows}
    return {s.id: chosen.get(s.id, s.default) for s in notice.switches}


async def granted_switches(
    conn: AsyncConnection, user_id: UUID, notice: ConsentNotice
) -> frozenset[str]:
    return frozenset(k for k, v in (await consent_state(conn, user_id, notice)).items() if v)


async def set_consent(
    conn: AsyncConnection,
    user_id: UUID,
    notice: ConsentNotice,
    switch: str,
    granted: bool,
    session_id: UUID | None = None,
) -> None:
    info = notice.switch(switch)
    if info.required and not granted:
        raise RequiredSwitch(switch)
    now = datetime.now(UTC)
    stmt = insert(t.consent).values(
        user_id=user_id,
        switch=switch,
        granted=granted,
        notice_version=notice.version,
        changed_at=now,
    )
    await conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[t.consent.c.user_id, t.consent.c.switch],
            set_={"granted": granted, "notice_version": notice.version, "changed_at": now},
        )
    )
    await append_event(
        conn,
        ConsentChanged(
            user_id=user_id,
            session_id=session_id,
            ts=now,
            payload=ConsentPayload(switch=info.id, granted=granted, notice_version=notice.version),
        ),
    )
