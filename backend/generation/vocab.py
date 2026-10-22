"""Content vocabulary from registry/content/themes.yaml."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.config import get_settings


@lru_cache
def themes() -> dict[str, Any]:
    path = Path(get_settings().registry_dir) / "content" / "themes.yaml"
    with path.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def stall_items(theme: str) -> list[str]:
    stalls: dict[str, list[str]] = themes()["stalls"]
    if theme == "mixed" or theme not in stalls:
        return sorted({item for items in stalls.values() for item in items})
    return list(stalls[theme])


def word_theme(theme: str) -> list[str] | None:
    words: dict[str, list[str]] = themes()["word_themes"]
    return list(words[theme]) if theme in words else None


def all_words() -> list[str]:
    words: dict[str, list[str]] = themes()["word_themes"]
    return sorted({w for ws in words.values() for w in ws})
