"""See, export and delete your data (docs/plan/14, "User rights in the app"; UW14).

Export is built on request from Postgres, Qdrant and the Markdown notes, and nothing is kept on
the server. API keys never leave: the export lists providers and last 4 characters only.

Delete removes Qdrant points, the notes folder and the LangGraph checkpoint threads first, then
cascades every Postgres row from `app.users` in one transaction that also writes the receipt. If
Qdrant is unreachable nothing is deleted, so a retry can finish the job.
"""

import datetime as dt
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.context import Services
from backend.contracts.events import DataExported, DataExportedPayload
from backend.db import tables as t
from backend.db.twin_store import append_event

# Every table that holds a user's rows. The test checks this against the database itself, so a
# new table with a user_id column can't be forgotten.
USER_TABLES: tuple[Table, ...] = (
    t.users,
    t.consent,
    t.goals,
    t.skill_pauses,
    t.llm_selection,
    t.llm_credentials,
    t.user_tokens,
    t.events,
    t.rounds,
    t.trials,
    t.dimension_state,
    t.history,
    t.acs_observations,
    t.life_context,
    t.sessions,
    t.decisions,
    t.traces,
    t.experiments,
    t.content_served,
)
# Never exported: encrypted keys and bearer-token hashes.
SECRET_COLUMNS = {"key_ciphertext", "nonce", "token_hash"}
EXPORT_SKIP = {"user_tokens"}


class DeletionIncomplete(RuntimeError):
    """A store couldn't be reached; nothing was deleted from Postgres, so the user can retry."""


def _plain(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, Range):
        return {"from": _plain(value.lower), "to": _plain(value.upper)}
    if isinstance(value, bytes):
        return None
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def user_hash(user_id: UUID) -> str:
    return hashlib.sha256(f"lodestar-deleted:{user_id}".encode()).hexdigest()


async def export_user(services: Services, user_id: UUID) -> dict[str, Any]:
    """Everything Lodestar holds about one user, as plain JSON-ready data."""
    tables: dict[str, list[dict[str, Any]]] = {}
    async with services.engine.connect() as conn:
        for table in USER_TABLES:
            if table.name in EXPORT_SKIP:
                continue
            columns = [c for c in table.c if c.name not in SECRET_COLUMNS]
            rows = await conn.execute(select(*columns).where(table.c.user_id == user_id))
            tables[f"{table.schema}.{table.name}"] = [
                {k: _plain(v) for k, v in row._mapping.items()} for row in rows
            ]
    memories: dict[str, list[dict[str, Any]]] = {}
    if services.memory is not None:
        for collection in ("episodic", "facts"):
            points = await services.memory.points(user_id, collection)  # filtered by user
            memories[collection] = [
                {"id": str(p.id), **{k: _plain(v) for k, v in (p.payload or {}).items()}}
                for p in points
            ]
    notes: dict[str, str] = {}
    if services.notes is not None:
        folder = services.notes.core_path(user_id).parent
        if folder.exists():
            for path in sorted(folder.rglob("*.md")):
                notes[str(path.relative_to(folder))] = path.read_text(encoding="utf-8")
    counts = {name: len(rows) for name, rows in tables.items()}
    counts |= {f"memories.{k}": len(v) for k, v in memories.items()}
    counts["notes"] = len(notes)
    async with services.engine.begin() as conn:
        await append_event(
            conn,
            DataExported(
                user_id=user_id,
                ts=dt.datetime.now(dt.UTC),
                payload=DataExportedPayload(counts=counts),
            ),
        )
    return {
        "exported_at": dt.datetime.now(dt.UTC).isoformat(),
        "about": "Everything Lodestar holds about you. API keys are never included.",
        "tables": tables,
        "memories": memories,
        "notes": notes,
    }


async def user_counts(engine: AsyncEngine, user_id: UUID) -> dict[str, int]:
    async with engine.connect() as conn:
        return {
            table.name: int(
                (
                    await conn.execute(
                        select(func.count()).select_from(table).where(table.c.user_id == user_id)
                    )
                ).scalar_one()
            )
            for table in USER_TABLES
        }


async def delete_user(services: Services, checkpointer: Any, user_id: UUID) -> dict[str, int]:
    """Delete everything, everywhere, and return the receipt counts (UW14)."""
    engine = services.engine
    async with engine.connect() as conn:
        sessions = [
            r.session_id
            for r in await conn.execute(
                select(t.sessions.c.session_id).where(t.sessions.c.user_id == user_id)
            )
        ]
    counts = {k: v for k, v in (await user_counts(engine, user_id)).items() if v}
    if services.memory is None:
        raise DeletionIncomplete("memory store unavailable")
    try:
        points = await services.memory.delete_user(user_id)
    except Exception as exc:
        raise DeletionIncomplete("memory store unavailable") from exc
    counts["memories"] = sum(points.values())
    counts["notes"] = services.notes.delete_user(user_id) if services.notes is not None else 0
    for session_id in sessions:
        await checkpointer.adelete_thread(str(session_id))
    counts["checkpoint_threads"] = len(sessions)
    async with engine.begin() as conn:
        await conn.execute(t.users.delete().where(t.users.c.user_id == user_id))  # cascades
        await conn.execute(
            t.deletion_receipts.insert().values(user_hash=user_hash(user_id), counts=counts)
        )
    return counts
