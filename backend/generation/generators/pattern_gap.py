"""Pattern Gap: 3x3 matrices built from rules by code, never by an LLM (docs/plan/08,
"Pattern Gap (matrices) generation"). The LLM may only reword the hint ladder. A solver infers the
rules from the eight visible cells and must find exactly one matching option: the answer."""

import random
from typing import Any, cast, get_args

from pydantic import BaseModel, Field

from backend.contracts.common import Contract
from backend.generation.generators.base import TextRequest, count
from backend.generation.schemas import (
    Attribute,
    Cell,
    Fill,
    MatrixPuzzle,
    PatternGapContent,
    Rule,
    RuleKind,
    Shape,
)

PUZZLES = 6
SHAPES: tuple[Shape, ...] = get_args(Shape)
FILLS: tuple[Fill, ...] = get_args(Fill)
ATTRIBUTES: tuple[Attribute, ...] = ("shape", "count", "fill", "rotation")
KINDS: dict[Attribute, tuple[RuleKind, ...]] = {
    "shape": ("distribution",),
    "fill": ("distribution",),
    "count": ("progression", "distribution"),
    "rotation": ("progression", "distribution"),
}
ROTATIONS = (0, 45, 90, 135, 180, 225, 270, 315)


class Hints(BaseModel):
    hints: list[str] = Field(min_length=3, max_length=3)


def _values(attr: Attribute, kind: RuleKind, rng: random.Random) -> list[Any]:
    """Three values for a varying attribute (one row's worth)."""
    if attr == "shape":
        return rng.sample(SHAPES, 3)
    if attr == "fill":
        return list(rng.sample(FILLS, 3))
    if attr == "count":
        return [1, 2, 3] if kind == "progression" else rng.sample([1, 2, 3], 3)
    step = rng.choice([45, 90])
    start = rng.choice([0, 45, 90])
    if kind == "progression":
        return [(start + i * step) % 360 for i in range(3)]
    return [(start + i * 90) % 360 for i in rng.sample(range(3), 3)]


def _grid(rules: list[Rule], fixed: dict[str, Any], rng: random.Random) -> list[list[Cell]]:
    values = {r.attribute: _values(r.attribute, r.kind, rng) for r in rules}
    rows = []
    for i in range(3):
        row = []
        for j in range(3):
            attrs = dict(fixed)
            for r in rules:
                v = values[r.attribute]
                # progression: same sequence each row; distribution: a Latin square.
                attrs[r.attribute] = v[j] if r.kind == "progression" else v[(i + j) % 3]
            row.append(Cell(**attrs))
        rows.append(row)
    return rows


def predict(grid: list[Cell]) -> dict[str, Any]:
    """The solver: infer each attribute's rule from the eight visible cells, predict the ninth."""
    rows = [grid[0:3], grid[3:6], grid[6:8]]
    out: dict[str, Any] = {}
    for attr in ATTRIBUTES:
        r0 = [getattr(c, attr) for c in rows[0]]
        r1 = [getattr(c, attr) for c in rows[1]]
        r2 = [getattr(c, attr) for c in rows[2]]
        if len(set(r0 + r1 + r2)) == 1:
            out[attr] = r0[0]
        elif r0 == r1 and r2 == r0[:2]:
            out[attr] = r0[2]  # the same progression in every row
        elif set(r0) == set(r1) and len(set(r0)) == 3:
            missing = set(r0) - set(r2)
            out[attr] = missing.pop() if len(missing) == 1 else None
        else:
            out[attr] = None
    return out


def matches(cell: Cell, prediction: dict[str, Any]) -> bool:
    return all(prediction[a] is not None and getattr(cell, a) == prediction[a] for a in ATTRIBUTES)


def _distractor(answer: Cell, changes: int, rng: random.Random) -> Cell:
    attrs = answer.model_dump()
    for attr in rng.sample(ATTRIBUTES, changes):
        if attr == "shape":
            attrs[attr] = rng.choice([s for s in SHAPES if s != answer.shape])
        elif attr == "fill":
            attrs[attr] = rng.choice([f for f in FILLS if f != answer.fill])
        elif attr == "count":
            attrs[attr] = rng.choice([n for n in (1, 2, 3) if n != answer.count])
        else:
            attrs[attr] = rng.choice([r for r in ROTATIONS if r != answer.rotation])
    return Cell(**attrs)


def template_hints(rules: list[Rule]) -> list[str]:
    first = rules[0]
    detail = {
        ("count", "progression"): "the number of shapes goes up by one",
        ("rotation", "progression"): "the shape turns by the same amount each step",
    }.get((first.attribute, first.kind), f"each {first.attribute} appears once")
    return [
        "Look along each row, from left to right.",
        f"Watch how the {first.attribute} changes across a row.",
        f"In every row, {detail}. Check the other features the same way.",
    ]


class PatternGapGenerator:
    game_id = "pattern_gap"
    schema = PatternGapContent

    def puzzle(self, n_rules: int, similarity: float, rng: random.Random) -> MatrixPuzzle:
        for _ in range(50):
            attrs = rng.sample(ATTRIBUTES, n_rules)
            rules = [Rule(attribute=a, kind=rng.choice(KINDS[a])) for a in attrs]
            fixed = {
                "shape": rng.choice(SHAPES),
                "count": rng.choice([1, 2, 3]),
                "fill": rng.choice(FILLS),
                "rotation": rng.choice([0, 90]),
            }
            rows = _grid(rules, fixed, rng)
            cells = [c for row in rows for c in row]
            answer = cells[8]
            changes = 1 if similarity >= 0.6 else 2
            options = [answer]
            while len(options) < 5:
                d = _distractor(answer, changes, rng)
                if d not in options:
                    options.append(d)
            rng.shuffle(options)
            p = MatrixPuzzle(
                grid=cells[:8],
                options=options,
                answer=options.index(answer),
                rules=rules,
                hints=template_hints(rules),
            )
            if not solve_errors(p):
                return p
        raise RuntimeError("could not build a uniquely solvable matrix")

    def build(
        self, knobs: dict[str, float], rng: random.Random, theme: str | None
    ) -> PatternGapContent:
        n_rules = count(knobs, "rules", 1, 1, 4)
        similarity = knobs.get("distractor_similarity", 0.5)
        return PatternGapContent(
            puzzles=[self.puzzle(n_rules, similarity, rng) for _ in range(PUZZLES)]
        )

    def text_request(self, content: Contract) -> TextRequest:
        c = cast(PatternGapContent, content)
        rules = [[r.model_dump() for r in p.rules] for p in c.puzzles]
        return TextRequest("pattern_gap", {"rules": rules}, _HintSets)

    def apply_text(self, content: Contract, text: BaseModel) -> PatternGapContent:
        c = cast(PatternGapContent, content)
        sets = cast(_HintSets, text).puzzles
        puzzles = [
            p.model_copy(update={"hints": sets[i].hints}) if i < len(sets) else p
            for i, p in enumerate(c.puzzles)
        ]
        return c.model_copy(update={"puzzles": puzzles})

    def check(self, content: Contract, knobs: dict[str, float]) -> list[str]:
        c = cast(PatternGapContent, content)
        errors = []
        for i, puzzle in enumerate(c.puzzles):
            errors += [f"puzzle {i}: {e}" for e in solve_errors(puzzle)]
            for hint in puzzle.hints:
                if len(hint) > 160:
                    errors.append(f"puzzle {i}: hint too long")
                lowered = hint.lower()
                if any(w in lowered for w in ("option", "answer is", "choose")):
                    errors.append(f"puzzle {i}: a hint gives the answer away")
        return errors

    def signature(self, content: Contract) -> str:
        c = cast(PatternGapContent, content)
        return "|".join(f"{p.rules}:{p.grid[0]}" for p in c.puzzles)


class _HintSets(BaseModel):
    puzzles: list[Hints]


def solve_errors(puzzle: MatrixPuzzle) -> list[str]:
    """Exactly one option may fit the inferred rules, and it must be the marked answer."""
    prediction = predict(puzzle.grid)
    if any(v is None for v in prediction.values()):
        return ["the rules can't be inferred from the visible cells"]
    fitting = [i for i, o in enumerate(puzzle.options) if matches(o, prediction)]
    if fitting != [puzzle.answer]:
        return [f"options fitting the rules: {fitting}, marked answer: {puzzle.answer}"]
    return []
