"""Spot the AI's Mistake (docs/plan/08): code builds a puzzle and its worked solution as structured
steps, plants at most one error, and a solver re-runs every step to confirm the error is real (or
that there is none). An LLM may only reword the steps; the numbers must survive unchanged.

About 70% of puzzles carry one planted error; the consent screen discloses that Najma is
sometimes wrong on purpose (docs/plan/14)."""

import operator
import random
from collections.abc import Callable
from typing import cast

from pydantic import BaseModel, Field

from backend.contracts.common import Contract
from backend.generation.generators.base import TextRequest, count
from backend.generation.schemas import MistakePuzzle, Op, SpotMistakeContent, Step
from backend.generation.vocab import themes

PUZZLES = 5
ERROR_SHARE = 0.7
OPS: dict[Op, Callable[[int, int], int]] = {
    "add": operator.add,
    "sub": operator.sub,
    "mul": operator.mul,
    "div": operator.floordiv,
}
SYMBOL: dict[Op, str] = {"add": "+", "sub": "-", "mul": "x", "div": "/"}
PRODUCTS = [("pens", 2, 6), ("notebooks", 3, 9), ("bottles of water", 1, 3), ("croissants", 1, 4)]


class StepTexts(BaseModel):
    puzzles: list[list[str]] = Field(description="Reworded step texts, same numbers, same order")


def _text(op: Op, a: int, b: int, result: int, label: str) -> str:
    return f"{label}: {a} {SYMBOL[op]} {b} = {result}."


def _shopping(
    n_steps: int, rng: random.Random
) -> tuple[str, list[tuple[Op, int | str, int | str, str]]]:
    """Plan of steps as (op, a, b, label); 'sN' refers to step N's result."""
    items = 2 if n_steps in (3, 4) else 3
    with_change = n_steps in (4, 6)
    names: list[str] = themes()["customer_names"]
    who = rng.choice(names)
    picked = rng.sample(PRODUCTS, items)
    plan: list[tuple[Op, int | str, int | str, str]] = []
    parts = []
    total = 0
    for name, lo, hi in picked:
        qty, price = rng.randint(2, 6), rng.randint(lo, hi)
        total += qty * price
        unit = "dinar" if price == 1 else "dinars"
        parts.append(f"{qty} {name} at {price} {unit} each")
        plan.append(("mul", qty, price, f"Cost of the {name}"))
    total_ref: int | str = "s0"
    for i in range(1, items):
        plan.append(("add", total_ref, f"s{i}", "Running total"))
        total_ref = f"s{len(plan) - 1}"
    question = f"{who} buys " + ", ".join(parts) + "."
    if with_change:
        paid = (total // 10 + 1) * 10  # the next round amount above the total
        plan.append(("sub", paid, total_ref, "Change"))
        question += f" They pay with {paid} dinars. How much change do they get?"
    else:
        question += " How much do they spend in total?"
    return question, plan


def _sequence(
    n_steps: int, rng: random.Random
) -> tuple[str, list[tuple[Op, int | str, int | str, str]]]:
    start, diff = rng.randint(2, 20), rng.randint(2, 9)
    shown = [start + i * diff for i in range(4)]
    ahead = n_steps - 1
    plan: list[tuple[Op, int | str, int | str, str]] = [("sub", shown[1], shown[0], "The gap")]
    prev: int | str = shown[-1]
    for k in range(ahead):
        plan.append(("add", prev, "s0", f"Number {k + 1} after {shown[-1]}"))
        prev = f"s{len(plan) - 1}"
    question = (
        f"The sequence goes {', '.join(map(str, shown))}. "
        f"What is the number {ahead} places after {shown[-1]}?"
    )
    return question, plan


def _execute(
    plan: list[tuple[Op, int | str, int | str, str]], error_at: int | None, kind: str, slip: int
) -> list[Step]:
    """Run the plan; at `error_at` the claimed result is wrong, and later steps carry it."""
    steps: list[Step] = []
    for i, (op, a_ref, b_ref, label) in enumerate(plan):
        a = steps[int(a_ref[1:])].result if isinstance(a_ref, str) else a_ref
        b = steps[int(b_ref[1:])].result if isinstance(b_ref, str) else b_ref
        result = OPS[op](a, b)
        shown_op = op
        if i == error_at:
            if kind == "wrong_operation":
                shown_op = "add" if op != "add" else "mul"
                result = OPS[shown_op](a, b)
                if result == OPS[op](a, b):  # e.g. 2 + 2 == 2 x 2: fall back to a slip
                    shown_op, result = op, result + slip
            else:
                result += slip
        steps.append(
            Step(op=op, a=a, b=b, result=result, text=_text(shown_op, a, b, result, label))
        )
    return steps


def step_errors(puzzle: MistakePuzzle) -> list[int]:
    """The solver: indexes of steps whose claimed result isn't what the operation gives."""
    return [i for i, s in enumerate(puzzle.steps) if OPS[s.op](s.a, s.b) != s.result]


class SpotMistakeGenerator:
    game_id = "spot_the_mistake"
    schema = SpotMistakeContent

    def puzzle(self, n_steps: int, subtlety: float, rng: random.Random) -> MistakePuzzle:
        kind = rng.choice(["shopping", "sequence"])
        question, plan = (_shopping if kind == "shopping" else _sequence)(n_steps, rng)
        has_error = rng.random() < ERROR_SHARE
        error_at = rng.randrange(len(plan)) if has_error else None
        # Subtle slips are off by 1 or 2; obvious ones by 10 or more.
        slip = rng.choice([1, 2, -1, -2]) if subtlety >= 0.6 else rng.choice([10, 20, -10])
        error_kind = (
            "arithmetic_slip" if subtlety >= 0.6 or rng.random() < 0.5 else "wrong_operation"
        )
        steps = _execute(plan, error_at, error_kind, slip)
        return MistakePuzzle(
            kind=kind,
            question=question,
            steps=steps,
            final_answer=steps[-1].result,
            has_error=has_error,
            error_step=error_at,
            error_kind=error_kind if has_error else None,
        )

    def build(
        self, knobs: dict[str, float], rng: random.Random, theme: str | None
    ) -> SpotMistakeContent:
        n_steps = count(knobs, "steps", 3, 3, 6)
        subtlety = knobs.get("error_subtlety", 0.5)
        return SpotMistakeContent(
            puzzles=[self.puzzle(n_steps, subtlety, rng) for _ in range(PUZZLES)]
        )

    def text_request(self, content: Contract) -> TextRequest:
        c = cast(SpotMistakeContent, content)
        steps = [[s.text for s in p.steps] for p in c.puzzles]
        return TextRequest("spot_the_mistake", {"steps": steps}, StepTexts)

    def apply_text(self, content: Contract, text: BaseModel) -> SpotMistakeContent:
        c = cast(SpotMistakeContent, content)
        rewritten = cast(StepTexts, text).puzzles
        puzzles = []
        for i, p in enumerate(c.puzzles):
            texts = rewritten[i] if i < len(rewritten) else []
            steps = [
                s.model_copy(update={"text": texts[j]}) if j < len(texts) else s
                for j, s in enumerate(p.steps)
            ]
            puzzles.append(p.model_copy(update={"steps": steps}))
        return c.model_copy(update={"puzzles": puzzles})

    def check(self, content: Contract, knobs: dict[str, float]) -> list[str]:
        c = cast(SpotMistakeContent, content)
        errors = []
        for i, p in enumerate(c.puzzles):
            wrong = step_errors(p)
            if p.has_error and wrong != [p.error_step]:
                errors.append(f"puzzle {i}: planted error at {p.error_step}, solver found {wrong}")
            if not p.has_error and wrong:
                errors.append(f"puzzle {i}: meant to be right, solver found errors at {wrong}")
            if p.final_answer != p.steps[-1].result:
                errors.append(f"puzzle {i}: final answer doesn't match the last step")
            for j, s in enumerate(p.steps):
                for number in (s.a, s.b, s.result):
                    if str(number) not in s.text:
                        errors.append(f"puzzle {i} step {j}: text lost the number {number}")
        return errors

    def signature(self, content: Contract) -> str:
        return " | ".join(p.question for p in cast(SpotMistakeContent, content).puzzles)
