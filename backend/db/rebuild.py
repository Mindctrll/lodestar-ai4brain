"""`make rebuild-twin USER=<id>`: recompute a user's profile from the event log."""

import argparse
import asyncio
from uuid import UUID

from backend.db.engine import get_async_engine
from backend.db.twin_store import rebuild_twin


async def _run(user_id: UUID) -> None:
    engine = get_async_engine()
    try:
        applied = await rebuild_twin(engine, user_id)
    finally:
        await engine.dispose()
    print(f"Rebuilt the Twin for {user_id} from {applied} events.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_id", type=UUID)
    asyncio.run(_run(parser.parse_args().user_id))


if __name__ == "__main__":
    main()
