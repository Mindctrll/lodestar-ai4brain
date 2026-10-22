"""Text versions of the games the registry marks `terminal: true` (UW19).

Each one plays the server's generated content (or, for code-content games, items made from the
round's seed) and records the same trials, with the same
right-or-wrong rule, as its browser plugin in `frontend/src/games/<id>/plugin.ts`. A test checks
that this list and the registry agree.
"""

import itertools
import random
import re
import statistics
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
GAMES_DIR = ROOT / "frontend" / "src" / "games"


class NoContent(Exception):
    """The round came without its generated items; the browser can still play it."""


class Stopped(Exception):
    """The user typed q."""


@dataclass
class Played:
    answers: list[dict[str, Any]] = field(default_factory=list)
    stopped: bool = False

    def add(
        self,
        stimulus: dict[str, Any],
        response: Any,
        correct: bool,
        rt_ms: float | None,
        practice: bool = False,
    ) -> None:
        self.answers.append(
            {
                "trial_index": len(self.answers),
                "practice": practice,
                "stimulus": stimulus,
                "response": response,
                "correct": correct,
                "rt_ms": None if rt_ms is None else round(rt_ms, 1),
                "ts": datetime.now(UTC).isoformat(),
            }
        )

    def scored(self) -> list[dict[str, Any]]:
        return [a for a in self.answers if not a["practice"]]

    def accuracy(self) -> float:
        s = self.scored()
        return sum(a["correct"] for a in s) / len(s) if s else 0.0


def _read(io: Io, prompt: str) -> str:
    try:
        line = io.read(prompt)
    except EOFError as exc:
        raise Stopped from exc
    if line.strip().lower() in ("q", "quit", "stop"):
        raise Stopped
    return line


def _config(game_id: str) -> dict[str, Any]:
    """The browser plugin's own config.yaml (trial count, deadline, word lists)."""
    try:
        return dict(yaml.safe_load((GAMES_DIR / game_id / "config.yaml").read_text()))
    except (OSError, TypeError, ValueError) as exc:
        raise NoContent from exc


def _feedback(io: Io, practice: bool, correct: bool) -> None:
    if practice:
        io.console.print("Right." if correct else "Not quite.")


# Market List (free word recall) ---------------------------------------------------------------

WORD = re.compile(r"[a-z]+")


def recalled(typed: str, words: list[str]) -> set[str]:
    """The browser's rule: any order, any separators, case ignored."""
    said = set(WORD.findall(typed.lower()))
    return {w for w in words if w.lower() in said}


# The browser plugin's own fallback list, used like the browser uses it: only when no words came.
FALLBACK_WORDS = GAMES_DIR / "market_list" / "config.yaml"


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
        "Lodestar solves a few puzzles step by step. Some solutions have one mistake, some don't. "
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


# Digits Back ----------------------------------------------------------------------------------


async def digits_back(io: Io, spec: dict[str, Any], played: Played) -> dict[str, float]:
    config = _config("digits_back")
    rng = random.Random(spec["seed"])
    speed_s = float(spec["knobs"].get("speed_ms", 900)) / 1000
    length = round(spec["knobs"].get("length", 4))
    practice_n = spec.get("practice_trials", 0)
    io.console.print(
        "Digits appear one at a time. Then type them in reverse order: 3 8 2 becomes 283."
    )
    _read(io, "Press Enter when you're ready (q to stop) ")
    for i in range(practice_n + config["trials"]):
        practice = i < practice_n
        digits = [rng.randint(0, 9) for _ in range(length)]
        await io.pause(0.5)
        with Live(Text(""), console=io.console, transient=True, refresh_per_second=20) as live:
            for d in digits:
                live.update(Text(f"   {d}", style="bold"))
                await io.pause(speed_s * 0.75)
                live.update(Text(""))
                await io.pause(speed_s * 0.25)
        start = io.clock()
        typed = re.sub(r"\D", "", _read(io, "The digits backwards (q to stop): "))
        rt = (io.clock() - start) * 1000
        correct = typed == "".join(str(d) for d in reversed(digits))
        if not practice:  # one up, one down
            length = max(
                config["min_length"], min(config["max_length"], length + (1 if correct else -1))
            )
        _feedback(io, practice, correct)
        played.add(
            {"digits": digits, "length": len(digits)}, {"typed": typed}, correct, rt, practice
        )
    right = [a["stimulus"]["length"] for a in played.scored() if a["correct"]]
    return {"span": max(right, default=0), "accuracy": played.accuracy()}


# Quick Maths ----------------------------------------------------------------------------------

TIMES, DIVIDE = "\u00d7", "\u00f7"  # as the browser records them
OPS = ["+", "-", TIMES, DIVIDE]


def make_sum(rng: random.Random, operations: int, top: int) -> tuple[int, int, str, int]:
    """The browser's sums: whole-number answers; `operations` 1 to 4 adds -, times and divide."""
    op = rng.choice(OPS[: max(1, min(4, operations))])
    a, b = rng.randint(1, top), rng.randint(1, top)
    if op == "-" and b > a:
        a, b = b, a
    if op in (TIMES, DIVIDE):
        b = rng.randint(1, min(12, top))
    if op == DIVIDE:
        a = b * rng.randint(1, max(1, top // b))
    answer = {"+": a + b, "-": a - b, TIMES: a * b, DIVIDE: a // b}[op]
    return a, b, op, answer


async def quick_maths(io: Io, spec: dict[str, Any], played: Played) -> dict[str, float]:
    config = _config("quick_maths")
    rng = random.Random(spec["seed"])
    operations = round(spec["knobs"].get("operations", 1))
    top = round(spec["knobs"].get("operand_max", 10))
    practice_n = spec.get("practice_trials", 0)
    io.console.print(
        f"Solve each sum as fast as you can and press Enter "
        f"({config['deadline_ms'] // 1000} seconds each)."
    )
    for i in range(practice_n + config["trials"]):
        practice = i < practice_n
        a, b, op, answer = make_sum(rng, operations, top)
        start = io.clock()
        typed = _read(io, f"{a} {op} {b} = ").strip()
        rt = (io.clock() - start) * 1000
        late = rt > config["deadline_ms"]
        correct = not late and typed.lstrip("-").isdigit() and int(typed) == answer
        if late:
            io.console.print("Too slow for that one.")
        _feedback(io, practice, correct)
        stimulus = {
            "a": a,
            "b": b,
            "op": op,
            "answer": answer,
            "deadline_ms": config["deadline_ms"],
        }
        played.add(
            stimulus, {"typed": typed} if typed else None, correct, None if late else rt, practice
        )
    s = played.scored()
    ms = sum(a["rt_ms"] or 0 for a in s)
    per_min = sum(a["correct"] for a in s) * 60_000 / ms if ms > 0 else 0.0
    return {"correct_per_min": per_min, "accuracy": played.accuracy()}


# Logic Lock -----------------------------------------------------------------------------------

ANSWERS = ["Yes", "No", "Can\u2019t tell"]  # as the browser records them
FORMS = ["forward", "backward", "affirm_consequent", "deny_antecedent"]


def make_lock(rng: random.Random, facts: list[list[str]], premises: int) -> dict[str, Any]:
    """A chain of if-then rules plus one fact, then a question (as the browser makes them)."""
    chosen = rng.sample(facts, min(len(facts), max(1, premises - 1) + 1))
    rules = [f"If {a[1]}, then {b[1]}." for a, b in itertools.pairwise(chosen)]
    first, last = chosen[0], chosen[-1]
    form = rng.choice(FORMS)
    fact, question, answer = {
        "forward": (f"{_cap(first[1])}.", f"Is it true that {last[1]}?", 0),
        "backward": (f"{_cap(last[0])}.", f"Is it true that {first[1]}?", 1),
        "affirm_consequent": (f"{_cap(last[1])}.", f"Is it true that {first[1]}?", 2),
        "deny_antecedent": (f"{_cap(first[0])}.", f"Is it true that {last[1]}?", 2),
    }[form]
    rng.shuffle(rules)
    return {"premises": [*rules, fact], "question": question, "answer": answer, "form": form}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def lock_answer(typed: str) -> int | None:
    said = typed.strip().lower().replace("\u2019", "'")
    for i, words in enumerate(
        (("1", "yes", "y"), ("2", "no", "n"), ("3", "can't tell", "cant tell"))
    ):
        if said in words:
            return i
    return None


async def logic_lock(io: Io, spec: dict[str, Any], played: Played) -> dict[str, float]:
    config = _config("logic_lock")
    rng = random.Random(spec["seed"])
    premises = round(spec["knobs"].get("premises", 2))
    practice_n = spec.get("practice_trials", 0)
    io.console.print(
        "Read the rules and the fact, then answer: Yes, No, or Can't tell. "
        "Use only what's written, not what you'd expect."
    )
    for i in range(practice_n + config["trials"]):
        practice = i < practice_n
        item = {**make_lock(rng, config["facts"], premises), "deadline_ms": config["deadline_ms"]}
        io.console.print()
        for line in item["premises"]:
            io.console.print(f"  {line}")
        io.console.print(Text(item["question"], style="bold"))
        start = io.clock()
        while (index := lock_answer(_read(io, "1 Yes, 2 No, 3 Can't tell (q to stop) "))) is None:
            io.console.print("Type 1, 2 or 3.")
        rt = (io.clock() - start) * 1000
        late = rt > config["deadline_ms"]
        correct = not late and index == item["answer"]
        _feedback(io, practice, correct)
        played.add(item, {"answer": ANSWERS[index]}, correct, rt, practice)
    out = {"accuracy": played.accuracy()}
    rts = [a["rt_ms"] for a in played.scored() if a["correct"]]
    if rts:
        out["median_rt_ms"] = statistics.median(rts)
    return out


Game = Callable[[Io, dict[str, Any], Played], Awaitable[dict[str, float]]]
GAMES: dict[str, Game] = {
    "market_list": market_list,
    "spot_the_mistake": spot_the_mistake,
    "digits_back": digits_back,
    "quick_maths": quick_maths,
    "logic_lock": logic_lock,
}


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
