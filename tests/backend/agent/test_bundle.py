"""Shipped models (docs/plan/10): an empty database gets the bundled models at start-up; a model
trained locally always wins."""

from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.db import tables as t
from backend.ml import bundle

NAMES = ("bundle_test_a", "bundle_test_b")


def _write(path: Path, version: str) -> None:
    models = [
        {"name": n, "version": version, "artefact_path": "models/x", "trained_at":
         "2026-10-21T08:00:00+00:00", "metrics": {"auc": 0.8}}
        for n in NAMES
    ]  # fmt: skip
    path.write_text(yaml.safe_dump({"models": models}), encoding="utf-8")


async def test_bundle_fills_an_empty_registry_once(aengine: AsyncEngine, tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    _write(path, "v1")
    try:
        assert await bundle.load(aengine, path) == list(NAMES)
        assert await bundle.load(aengine, path) == []  # already there: nothing added twice

        # A model trained here is active, so a newer bundle doesn't replace it.
        _write(path, "v2")
        assert await bundle.load(aengine, path) == []
        async with aengine.connect() as conn:
            rows = (
                await conn.execute(
                    select(t.ml_models.c.name, t.ml_models.c.version, t.ml_models.c.metrics).where(
                        t.ml_models.c.name.in_(NAMES)
                    )
                )
            ).all()
        assert sorted((r.name, r.version) for r in rows) == [(n, "v1") for n in NAMES]
        assert all(r.metrics == {"auc": 0.8} for r in rows)
    finally:
        async with aengine.begin() as conn:
            await conn.execute(delete(t.ml_models).where(t.ml_models.c.name.in_(NAMES)))


async def test_missing_bundle_is_a_no_op(aengine: AsyncEngine, tmp_path: Path) -> None:
    assert await bundle.load(aengine, tmp_path / "absent.yaml") == []
