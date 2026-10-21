"""Load and validate the YAML registry."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.config import get_settings
from backend.registry.models import Registry


def _read(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_registry_from(root: Path) -> Registry:
    games = [_read(p) for p in sorted((root / "games").glob("*.yaml"))]
    return Registry.model_validate(
        {
            "dimensions": _read(root / "dimensions.yaml"),
            "games": games,
            "providers": _read(root / "llm_providers.yaml"),
            "batteries": _read(root / "batteries.yaml"),
            "consent": _read(root / "consent.yaml"),
            "priors": _read(root / "priors.yaml") if (root / "priors.yaml").exists() else None,
            "practice": (
                _read(root / "practice.yaml") if (root / "practice.yaml").exists() else None
            ),
        }
    )


def load_knowledge_items() -> list[dict[str, Any]]:
    """Team-written coaching tips for the shared knowledge collection."""
    items: list[dict[str, Any]] = _read(Path(get_settings().registry_dir) / "knowledge.yaml")
    return items


@lru_cache
def load_registry() -> Registry:
    return load_registry_from(Path(get_settings().registry_dir))
