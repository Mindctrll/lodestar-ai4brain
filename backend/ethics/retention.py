"""The daily retention job (docs/plan/14, Retention; 04, "Retention").

- Traces and LangGraph checkpoints older than 30 days are deleted.
- Trial events, trials, rounds and profile history are kept for 12 months. Before a monthly
  partition of `twin.events` past that is dropped, every affected user gets a `twin.snapshot`
  event (their current skill state and remaining history), so the profile can still be rebuilt
  from events.
- Upcoming monthly partitions are created ahead of time.

Only counts are logged. Run it with `make retention`.
"""

import asyncio
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Text, cast, delete, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from backend.contracts.events import HistoryRow, TwinSnapshotPayload, TwinSnapshotTaken
from backend.contracts.twin import DimensionState
from backend.db import tables as t
from backend.db.twin_store import append_event, lock_user

log = logging.getLogger(__name__)

TRACE_DAYS = 30
CHECKPOINT_DAYS = 30
EVENT_MONTHS = 12
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")
_PART = re.compile(r"^events_(\d{4})_(\d{2})$")


def months_before(day: date, months: int) -> date:
    """The first day of the month `months` before `day`'s month."""
    index = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


async def _partitions(conn: AsyncConnection) -> list[tuple[str, date]]:
    rows = await conn.execute(
        text(
            "SELECT c.relname FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "JOIN pg_namespace n ON n.oid = p.relnamespace "
            "WHERE n.nspname = 'twin' AND p.relname = 'events'"
        )
    )
    out = []
    for (name,) in rows:
        if m := _PART.match(name):
            out.append((name, date(int(m.group(1)), int(m.group(2)), 1)))
    return sorted(out, key=lambda p: p[1])


async def snapshot(conn: AsyncConnection, user_id: UUID, now: datetime, until: datetime) -> None:
    """One twin.snapshot event with the user's current state and history; `until` is where the
    dropped events end."""
    await lock_user(conn, user_id)
    dims = [
        DimensionState(dim=r.dim, mu=r.mu, sigma=r.sigma, n=r.n, last_practised=r.last_practised)
        for r in await conn.execute(
            select(t.dimension_state).where(t.dimension_state.c.user_id == user_id)
        )
    ]
    history = [
        HistoryRow(day=r.day, dim=r.dim, mu=r.mu, sigma=r.sigma, n=r.n)
        for r in await conn.execute(select(t.history).where(t.history.c.user_id == user_id))
    ]
    await append_event(
        conn,
        TwinSnapshotTaken(
            user_id=user_id,
            ts=now,
            payload=TwinSnapshotPayload(dims=dims, history=history, covers_until=until),
        ),
    )


async def run_retention(engine: AsyncEngine, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    counts: dict[str, int] = {}

    async def removed(conn: AsyncConnection, key: str, statement: Any) -> None:
        result = await conn.execute(statement)
        counts[key] = counts.get(key, 0) + max(result.rowcount or 0, 0)

    async with engine.begin() as conn:
        await conn.execute(text("SELECT twin.ensure_event_partitions(0, 3)"))
        await removed(
            conn, "traces", delete(t.traces).where(t.traces.c.ts < now - timedelta(days=TRACE_DAYS))
        )
        old_threads = select(cast(t.sessions.c.session_id, Text)).where(
            t.sessions.c.started_at < now - timedelta(days=CHECKPOINT_DAYS)
        )
        compiled = old_threads.compile(compile_kwargs={"literal_binds": True})
        for table in CHECKPOINT_TABLES:
            await removed(
                conn, table, text(f"DELETE FROM public.{table} WHERE thread_id IN ({compiled})")
            )

    cutoff_day = months_before(now.date(), EVENT_MONTHS)
    cutoff = datetime(cutoff_day.year, cutoff_day.month, 1, tzinfo=UTC)
    async with engine.begin() as conn:
        old_parts = [name for name, month in await _partitions(conn) if month < cutoff_day]
        users: set[UUID] = set()
        for name in old_parts:
            users |= {
                r[0] for r in await conn.execute(text(f"SELECT DISTINCT user_id FROM twin.{name}"))
            }
        users |= {
            r[0]
            for r in await conn.execute(
                text("SELECT DISTINCT user_id FROM twin.events_default WHERE ts < :c"),
                {"c": cutoff},
            )
        }
        await removed(conn, "trials", delete(t.trials).where(t.trials.c.ts < cutoff))
        await removed(conn, "rounds", delete(t.rounds).where(t.rounds.c.started_at < cutoff))
        await removed(conn, "history", delete(t.history).where(t.history.c.day < cutoff_day))
        for user_id in sorted(users):
            await snapshot(conn, user_id, now, cutoff)
        counts["snapshots"] = len(users)
        await removed(
            conn,
            "events",
            text("DELETE FROM twin.events_default WHERE ts < :c").bindparams(c=cutoff),
        )
        for name in old_parts:
            events = (await conn.execute(text(f"SELECT count(*) FROM twin.{name}"))).scalar_one()
            counts["events"] = counts.get("events", 0) + int(events)
            await conn.execute(text(f"ALTER TABLE twin.events DETACH PARTITION twin.{name}"))
            await conn.execute(text(f"DROP TABLE twin.{name}"))
        counts["partitions_dropped"] = len(old_parts)
    log.info("retention removed %s", {k: v for k, v in counts.items() if v})
    return counts


async def main() -> None:  # pragma: no cover - CLI
    from backend.db.engine import get_async_engine

    engine = get_async_engine()
    print(await run_retention(engine))
    await engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
