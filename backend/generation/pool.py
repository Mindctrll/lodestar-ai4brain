"""`make pool`: keep agent.content_pool filled so play never waits on an LLM (docs/plan/08)."""

import argparse
import asyncio

from backend.db.engine import get_async_engine
from backend.generation.generators.registry import GENERATORS
from backend.generation.pipeline import ContentService
from backend.registry.loader import load_registry


async def _run(per_level: int) -> None:
    registry = load_registry()
    engine = get_async_engine()
    service = ContentService(engine, llm=None)
    try:
        for game_id in GENERATORS:
            game = registry.game(game_id)
            added = await service.fill_pool(game_id, per_level=per_level, knobs_at=game.knobs_at)
            print(f"{game_id}: added {added} items")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-level", type=int, default=30)
    asyncio.run(_run(parser.parse_args().per_level))


if __name__ == "__main__":
    main()
