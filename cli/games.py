"""Text versions of the games the registry marks `terminal: true` (UW19).

Each one plays the server's generated content and records the same trials, with the same
right-or-wrong rule, as its browser plugin in `frontend/src/games/<id>/plugin.ts`. A test checks
that this list and the registry agree.
"""

import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from rich.live import Live
from rich.text import Text

from cli.client import Io

ROOT = Path(__file__).resolve().parents[1]


class NoContent(Exception):
    """The round came without its generated items; the browser can still play it."""


class Stopped(Exception):
    """The user typed q."""


@dataclass
class Played:
    answers: list[dict[str, Any]] = field(default_factory=list)
    stopped: bool = False

    def add(self, stimulus: dict[str, Any], response: Any, correct: bool, rt_ms: float) -> None:
        self.answers.append(
            {
                "trial_index": len(self.answers),
                "stimulus": stimulus,
                "response": response,
                "correct": correct,
                "rt_ms": round(rt_ms, 1),
                "ts": datetime.now(UTC).isoformat(),
            }
        )


def _read(io: Io, prompt: str) -> str:
    try:
        line = io.read(prompt)
    except EOFError as exc:
        raise Stopped from exc
    if line.strip().lower() in ("q", "quit", "stop"):
        raise Stopped
    return line


# Market List (free word recall) ---------------------------------------------------------------

WORD = re.compile(r"[a-z]+")


def recalled(typed: str, words: list[str]) -> set[str]:
    """The browser's rule: any order, any separators, case ignored."""
    said = set(WORD.findall(typed.lower()))
    return {w for w in words if w.lower() in said}


# The browser plugin's own fallback list, used like the browser uses it: only when no words came.
FALLBACK_WORDS = ROOT / "frontend" / "src" / "games" / "market_list" / "config.yaml"


def fallback_list(spec: dict[str, Any]) -> list[str]:
    try:
        words = list(yaml.safe_load(FALLBACK_WORDS.read_text())["fallback_words"])
    except (OSError, KeyError, TypeError) as exc:
        raise NoContent from exc
    random.Random(spec["seed"]).shuffle(words)
    return [str(w) for w in words[: round(spec["knobs"].get("list_length", 8))]]


async def market_list(io: Io, spec: dict[str, Any], played: Played) -> dict[str, float]:
    lists: list[list[str]] = (spec.get("content") or {}).get("lists") or [fallback_list(spec)]
    speed_s = float(spec["knobs"].get("speed_ms", 1200)) / 1000
    io.console.print("Words will flash one at a time. Afterwards, type every word you remember.")
    for words in lists:
        _read(io, "Press Enter when you're ready (q to stop) ")
        with Live(Text(""), console=io.console, transient=True, refresh_per_second=20) as live:
            for word in words:
                live.update(Text(f"   {word}", style="bold"))
                await io.pause(speed_s * 0.8)
                live.update(Text(""))
                await io.pause(speed_s * 0.2)
        start = io.clock()
        got = recalled(_read(io, "The words you remember, in any order: "), words)
        rt = (io.clock() - start) * 1000
        for i, word in enumerate(words):
            stimulus = {"word": word, "position": i, "list_length": len(words)}
            played.add(stimulus, {"typed": word in got}, word in got, rt)
    right = sum(a["correct"] for a in played.answers)
    return {"items_recalled": right, "recall_share": right / max(1, len(played.answers))}


# Spot the AI's Mistake ------------------------------------------------------------------------


async def spot_the_mistake(io: Io, spec: dict[str, Any], played: Played) -> dict[str, float]:
    puzzles: list[dict[str, Any]] = (spec.get("content") or {}).get("puzzles") or []
    if not puzzles:
        raise NoContent
    io.console.print(
        "Najma solves a few puzzles step by step. Some solutions have one mistake, some don't. "
        "Find the wrong step, or say they're all right."
    )
    for puzzle in puzzles:
        steps = puzzle["steps"]
        io.console.print(Text(f"\n{puzzle['question']}", style="bold"))
        for i, step in enumerate(steps):
            io.console.print(f"  {i + 1}. {step['text']}")
        io.console.print("  0. All steps are right")
        start = io.clock()
        while True:
            raw = _read(io, "Which step is wrong? (0 if none, q to stop) ").strip()
            if raw.isdigit() and int(raw) <= len(steps):
                break
            io.console.print(f"Type a step number from 1 to {len(steps)}, or 0.")
        rt = (io.clock() - start) * 1000
        flagged = None if int(raw) == 0 else int(raw) - 1
        has_error = bool(puzzle["has_error"])
        correct = flagged == puzzle["error_step"] if has_error else flagged is None
        stimulus = {
            "has_error": has_error,
            "error_step": puzzle["error_step"],
            "steps": len(steps),
        }
        played.add(stimulus, {"flagged": flagged}, correct, rt)
    rates = []
    for kind in (True, False):
        group = [a for a in played.answers if a["stimulus"]["has_error"] is kind]
        if group:
            rates.append(sum(a["correct"] for a in group) / len(group))
    total = len(played.answers)
    return {
        "balanced_accuracy": sum(rates) / len(rates) if rates else 0.0,
        "accuracy": sum(a["correct"] for a in played.answers) / total if total else 0.0,
    }


Game = Callable[[Io, dict[str, Any], Played], Awaitable[dict[str, float]]]
GAMES: dict[str, Game] = {"market_list": market_list, "spot_the_mistake": spot_the_mistake}


async def play(io: Io, spec: dict[str, Any]) -> dict[str, Any]:
    """Play one round and return the arguments for the `finish_round` tool. Raises NoContent if
    the round can't be played as text."""
    started = datetime.now(UTC)
    played = Played()
    metrics: dict[str, float] = {}
    try:
        metrics = await GAMES[spec["game_id"]](io, spec, played)
    except Stopped:
        played.stopped = True
    return {
        "round_id": spec["round_id"],
        "answers": played.answers,
        "metrics": metrics,
        "status": "stopped" if played.stopped else "completed",
        "stop_reason": "user" if played.stopped else None,
        "started_at": started.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
    }
