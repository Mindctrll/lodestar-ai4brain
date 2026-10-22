"""Ship the trained models with the repo (docs/plan/10).

`agent.ml_models` in Postgres is where the app reads its active models. Training writes there and
under `models/`; this module copies the active rows to `models/registry.yaml` so they can be
committed next to their files, and loads them back into an empty database at start-up. A fresh
clone then has the growth forecast and the engagement model without the 3.1 GB of training data.
Postgres stays the system of record: the file is a release artefact, read once.

    python -m backend.ml.bundle export   # after `make ml-train` / `make ml-engagement`
    python -m backend.ml.bundle load     # what start-up does
"""

import asyncio
import datetime as dt
import logging
import sys
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.db import tables as t
from backend.db.engine import get_async_engine

log = logging.getLogger(__name__)

BUNDLE = Path("models/registry.yaml")
HEADER = (
    "# The trained models that ship with Lodestar (docs/plan/10). Written by\n"
    "# `make models-export` from agent.ml_models; loaded into an empty database at start-up\n"
    "# (backend/ml/bundle.py). Do not edit by hand.\n"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    models: list[dict[str, Any]] = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(
        "models", []
    )
    return models


async def export(engine: AsyncEngine, path: Path = BUNDLE) -> int:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(t.ml_models)
                .where(t.ml_models.c.active.is_(True))
                .order_by(t.ml_models.c.name)
            )
        ).all()
    models = [
        {
            "name": r.name,
            "version": r.version,
            "artefact_path": r.artefact_path,
            "trained_at": r.trained_at.isoformat(),
            "metrics": r.metrics,
        }
        for r in rows
    ]
    text = HEADER + yaml.safe_dump({"models": models}, sort_keys=False, width=100)
    await asyncio.to_thread(_write, path, text)
    return len(models)


async def load(engine: AsyncEngine, path: Path = BUNDLE) -> list[str]:
    """Add each bundled model whose name has no active model yet; return the names added.
    A model trained here always wins over the bundled one."""
    bundled = await asyncio.to_thread(_read, path)
    if not bundled:
        return []
    added = []
    async with engine.begin() as conn:
        active = set(
            (
                await conn.execute(select(t.ml_models.c.name).where(t.ml_models.c.active.is_(True)))
            ).scalars()
        )
        for m in bundled:
            if m["name"] in active:
                continue
            await conn.execute(
                t.ml_models.insert().values(
                    name=m["name"],
                    version=m["version"],
                    artefact_path=m["artefact_path"],
                    trained_at=dt.datetime.fromisoformat(m["trained_at"]),
                    metrics=m["metrics"],
                    active=True,
                )
            )
            added.append(m["name"])
    if added:
        log.info("loaded bundled models: %s", ", ".join(added))
    return added


async def _main(command: str) -> None:
    engine = get_async_engine()
    try:
        if command == "export":
            print(f"wrote {await export(engine)} models to {BUNDLE}")
        elif command == "load":
            added = await load(engine)
            print(f"loaded {', '.join(added)}" if added else "nothing to load")
        else:
            raise SystemExit("usage: python -m backend.ml.bundle export|load")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1] if len(sys.argv) > 1 else ""))
