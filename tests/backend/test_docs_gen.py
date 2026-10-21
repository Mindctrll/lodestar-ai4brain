"""WP4.3: the generated docs have no missing field and match what's on disk (`make docs`)."""

from backend.docs_gen import problems, render, stale
from backend.registry.loader import load_registry


def test_docs_complete_and_up_to_date() -> None:
    reg = load_registry()
    assert problems(reg) == []
    pages = render(reg)
    assert len(pages) == len(reg.dimensions) + 4
    assert stale(pages) == [], "docs/generated is out of date: run `make docs`"
