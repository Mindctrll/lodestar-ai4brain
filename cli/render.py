"""How Lodestar looks in the terminal: replies with their citations, questions with their facts, and
the profile and goals tables. Numbers are rounded the way the web app rounds them."""

import math
import re
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

CITATION = re.compile(r"\[(?:[FDMK]\d+)(?:,\s*[FDMK]\d+)*\]")
BAR_CELLS = 10


def pct(x: float) -> int:
    """Half up, like the web app's Math.round (Python's round() would round 64.5 to 64)."""
    return math.floor(x + 0.5)


def cited(text: str) -> Text:
    """A sentence with its citations dimmed: they say which fact a number comes from."""
    out = Text()
    last = 0
    for m in CITATION.finditer(text):
        out.append(text[last : m.start()])
        out.append(m.group(0), style="dim")
        last = m.end()
    out.append(text[last:])
    return out


def coach_name(persona: str) -> str:
    return persona.replace("_", " ").title()


def say(console: Console, persona: str, sentences: list[str]) -> None:
    if not sentences:
        return
    line = Text.assemble(("Lodestar", "bold magenta"), f" ({coach_name(persona)}): ")
    line.append_text(cited(" ".join(s.strip() for s in sentences)))
    console.print(line)


def question(console: Console, message: str) -> None:
    """A write tool's question: the question, then the facts its numbers come from."""
    ask, _, facts = message.partition("\n\n")
    console.print(Text.assemble(("Lodestar", "bold magenta"), ": ", cited(ask)))
    for line in facts.splitlines():
        console.print(Text(f"  {line}", style="dim"))


def facts(console: Console, items: list[dict[str, Any]]) -> None:
    for f in items:
        console.print(Text.assemble((f"[{f['id']}] ", "dim"), f["text"]))


def bar(percent: float) -> str:
    filled = min(BAR_CELLS, max(0, pct(percent / (100 / BAR_CELLS))))
    return "▓" * filled + "░" * (BAR_CELLS - filled)


def profile_table(skills: list[dict[str, Any]]) -> Table:
    table = Table(box=None, pad_edge=False, show_header=True, header_style="bold")
    table.add_column("Skill")
    table.add_column("Estimate", justify="right")
    table.add_column("80% range", justify="right")
    table.add_column("")
    measured = [s for s in skills if s["rounds"] > 0]
    for s in sorted(measured, key=lambda s: s["percent"], reverse=True):
        style = "dim" if s["still_learning"] else ""
        note = "  still learning about you" if s["still_learning"] else ""
        table.add_row(
            s["name"],
            f"{pct(s['percent'])}%",
            f"({pct(s['low'])}-{pct(s['high'])})",
            bar(s["percent"]) + note,
            style=style,
        )
    return table


def goals_table(goals: list[dict[str, Any]]) -> Table:
    table = Table(box=None, pad_edge=False, show_header=True, header_style="bold")
    for name, justify in (
        ("Skill", "left"),
        ("Goal", "right"),
        ("Range now", "right"),
        ("By", "left"),
        ("Rounds left", "right"),
    ):
        table.add_column(name, justify=justify)  # type: ignore[arg-type]
    for g in goals:
        now = f"±{pct(g['range_now'])}" if g["range_now"] is not None else "not measured yet"
        left = "met" if g["met"] else (str(g["rounds_left"]) if g["rounds_left"] else "-")
        table.add_row(g["name"], f"±{g['target']}", now, g["due"], left)
    return table
