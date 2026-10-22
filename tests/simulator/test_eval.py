"""WP4.2: `make eval` runs every experiment of docs/plan/15 and writes a figure for each (tiny
sizes, stub coach; experiment 11 is skipped when Postgres is down)."""

import os
import re
from pathlib import Path

import pytest

from simulator.eval import main

BASE = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://lodestar:lodestar@localhost:5442/lodestar_test"
)


def test_eval_writes_every_figure_and_the_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVAL_DATABASE_URL", BASE + "_eval")
    main(["--quick", "--stub-coach", "--out", str(tmp_path)])
    summary = (tmp_path / "eval_summary.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d+) \|.*\| (pass|FAIL|reported|skipped) \| (.+) \|$", summary, re.M)
    assert [int(n) for n, _, _ in rows] == list(range(1, 13))
    for _, status, figure in rows:
        if status != "skipped":
            name = figure.split("](")[1].rstrip(")")
            assert (tmp_path / name).stat().st_size > 0, name
