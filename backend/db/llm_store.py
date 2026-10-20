"""Saved API keys (encrypted) and the active LLM selection (docs/plan/04; AGENTS.md rule 9)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from backend.contracts.events import LlmSelectionChanged, LlmSelectionPayload
from backend.contracts.llm import CredentialSummary, LlmSelection
from backend.db import tables as t
from backend.db.twin_store import append_event
from backend.llm.vault import SealedKey


@dataclass(frozen=True)
class StoredCredential:
    credential_id: UUID
    ciphertext: bytes
    nonce: bytes
    status: str


async def save_credential(
    conn: AsyncConnection, user_id: UUID, provider: str, sealed: SealedKey, status: str
) -> UUID:
    values = {
        "key_ciphertext": sealed.ciphertext,
        "nonce": sealed.nonce,
        "master_key_version": sealed.master_key_version,
        "key_last4": sealed.last4,
        "status": status,
        "checked_at": func.now(),
    }
    row = await conn.execute(
        pg_insert(t.llm_credentials)
        .values(user_id=user_id, provider=provider, **values)
        .on_conflict_do_update(index_elements=["user_id", "provider"], set_=values)
        .returning(t.llm_credentials.c.credential_id)
    )
    credential_id: UUID = row.scalar_one()
    return credential_id


async def get_credential(
    conn: AsyncConnection, user_id: UUID, provider: str
) -> StoredCredential | None:
    row = (
        await conn.execute(
            select(t.llm_credentials).where(
                t.llm_credentials.c.user_id == user_id, t.llm_credentials.c.provider == provider
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return StoredCredential(row.credential_id, row.key_ciphertext, row.nonce, row.status)


async def set_credential_status(
    conn: AsyncConnection, user_id: UUID, provider: str, status: str
) -> None:
    await conn.execute(
        t.llm_credentials.update()
        .where(t.llm_credentials.c.user_id == user_id, t.llm_credentials.c.provider == provider)
        .values(status=status, checked_at=func.now())
    )


async def delete_credential(conn: AsyncConnection, user_id: UUID, provider: str) -> bool:
    result = await conn.execute(
        t.llm_credentials.delete().where(
            t.llm_credentials.c.user_id == user_id, t.llm_credentials.c.provider == provider
        )
    )
    return bool(result.rowcount)


async def credential_summaries(conn: AsyncConnection, user_id: UUID) -> list[CredentialSummary]:
    rows = await conn.execute(
        select(
            t.llm_credentials.c.provider, t.llm_credentials.c.key_last4, t.llm_credentials.c.status
        )
        .where(t.llm_credentials.c.user_id == user_id)
        .order_by(t.llm_credentials.c.provider)
    )
    return [
        CredentialSummary(provider=r.provider, key_last4=r.key_last4, status=r.status) for r in rows
    ]


async def get_selection(conn: AsyncConnection, user_id: UUID, local_model: str) -> LlmSelection:
    row = (
        await conn.execute(select(t.llm_selection).where(t.llm_selection.c.user_id == user_id))
    ).one_or_none()
    if row is None:
        return LlmSelection(mode="local", provider="ollama", model=local_model)
    credential = None
    if row.mode == "hosted":
        stored = await get_credential(conn, user_id, row.provider)
        credential = stored.credential_id if stored else None
    return LlmSelection(
        mode=row.mode, provider=row.provider, model=row.model, credential_id=credential
    )


async def set_selection(conn: AsyncConnection, user_id: UUID, selection: LlmSelection) -> None:
    values = {
        "mode": selection.mode,
        "provider": selection.provider,
        "model": selection.model,
        "updated_at": func.now(),
    }
    await conn.execute(
        pg_insert(t.llm_selection)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(index_elements=["user_id"], set_=values)
    )
    await append_event(
        conn,
        LlmSelectionChanged(
            user_id=user_id,
            ts=datetime.now(UTC),
            payload=LlmSelectionPayload(
                mode=selection.mode, provider=selection.provider, model=selection.model
            ),
        ),
    )
