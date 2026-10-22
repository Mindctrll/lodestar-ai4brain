"""Memory notes for the demo user (docs/plan/04): a few core.md lines and some remembered moments
and facts in Qdrant, so the Memory page has something to show. Runs where the app's memory lives,
inside the backend container: `make seed` calls it after `backend.db.seed`."""

import asyncio
from datetime import UTC, datetime, timedelta

from qdrant_client import AsyncQdrantClient
from sqlalchemy import select

from backend.config import get_settings
from backend.db import tables as t
from backend.db.engine import get_engine
from backend.db.seed import DEMO_NAME
from backend.memory.embeddings import Embedder
from backend.memory.notes import Notes
from backend.memory.store import MemoryStore

CORE = [
    "Plays best in the evening, after work.",
    "Wants working memory solid before exam week.",
    "Likes the Detective story more than plain drills.",
    "Prefers short sessions on busy days.",
    "Calm, short coaching works best.",
]
# (days ago, collection, kind, text)
MOMENTS = [
    (2, "episodic", "moment", "Slept badly before the session and still beat their Echo record."),
    (
        5,
        "episodic",
        "preference",
        "Turned down two spatial games in a row; asked for number puzzles.",
    ),
    (9, "episodic", "milestone", "Finished the morning-or-evening experiment: evening won."),
    (12, "episodic", "milestone", "Reached the inhibition goal a week early."),
    (26, "episodic", "moment", "Back from holiday; sessions were shorter that week."),
    (9, "facts", "fact", "Best time of day: evening, from their own experiment."),
    (20, "facts", "fact", "Tends to slow down after about a quarter of an hour of play."),
]


async def seed_memory() -> None:
    settings = get_settings()
    with get_engine().connect() as conn:
        user_id = conn.execute(
            select(t.users.c.user_id).where(t.users.c.display_name == DEMO_NAME)
        ).scalar_one()
    Notes(settings.memory_dir).write_core(user_id, CORE)
    memory = MemoryStore(AsyncQdrantClient(url=settings.qdrant_url, timeout=10), Embedder())
    await memory.ensure_collections()
    now = datetime.now(UTC)
    for days, collection, kind, text in MOMENTS:
        await memory.write(
            user_id, text, collection=collection, kind=kind,  # type: ignore[arg-type]
            importance=0.7, created_at=now - timedelta(days=days), confidence=0.8,
        )  # fmt: skip
    print(f"Wrote {len(CORE)} core lines and {len(MOMENTS)} memories for {DEMO_NAME}")


if __name__ == "__main__":
    asyncio.run(seed_memory())
