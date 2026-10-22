"""Content schemas, one per generated game (docs/plan/08, "Schemas").

Structure (what's asked, what's right) is built by code; only the `line`, `hints` and step `text`
fields are written by an LLM, and validators check them against the structure.
"""

from typing import Literal

from pydantic import Field

from backend.contracts.common import Contract

# Market Rush ----------------------------------------------------------------------------------


class MarketOrder(Contract):
    customer: str = Field(max_length=20)
    items: list[str] = Field(min_length=1, max_length=6)
    line: str = Field(max_length=240)


class OrderChange(Contract):
    customer: str
    remove: str
    add: str
    line: str = Field(max_length=240)


class MarketScene(Contract):
    orders: list[MarketOrder] = Field(min_length=1, max_length=4)
    changes: list[OrderChange] = Field(default_factory=list)


class MarketRushContent(Contract):
    theme: Literal["fruit", "spices", "bakery", "pottery", "mixed"]
    scenes: list[MarketScene] = Field(min_length=1, max_length=6)


# Market List --------------------------------------------------------------------------------


class MarketListContent(Contract):
    theme: str = Field(max_length=30)
    lists: list[list[str]] = Field(min_length=1, max_length=4)


# Pattern Gap (matrices) ---------------------------------------------------------------------

Shape = Literal["circle", "square", "triangle", "diamond", "star"]
Fill = Literal["empty", "striped", "solid"]


class Cell(Contract):
    shape: Shape
    count: int = Field(ge=1, le=3)
    fill: Fill
    rotation: int = Field(ge=0, lt=360)


Attribute = Literal["shape", "count", "fill", "rotation"]
RuleKind = Literal["constant", "progression", "distribution"]


class Rule(Contract):
    attribute: Attribute
    kind: RuleKind


class MatrixPuzzle(Contract):
    grid: list[Cell] = Field(
        min_length=8, max_length=8, description="Row by row; the 9th is missing"
    )
    options: list[Cell] = Field(min_length=4, max_length=6)
    answer: int = Field(ge=0)
    rules: list[Rule]
    hints: list[str] = Field(min_length=3, max_length=3, description="From gentle to strong")


class PatternGapContent(Contract):
    puzzles: list[MatrixPuzzle] = Field(min_length=1, max_length=10)


# Spot the AI's Mistake ----------------------------------------------------------------------

Op = Literal["add", "sub", "mul", "div"]


class Step(Contract):
    op: Op
    a: int
    b: int
    result: int = Field(description="What Lodestar claims; wrong in the planted step")
    text: str = Field(max_length=200)


class MistakePuzzle(Contract):
    kind: Literal["shopping", "sequence", "sharing"]
    question: str = Field(max_length=300)
    steps: list[Step] = Field(min_length=2, max_length=7)
    final_answer: int
    has_error: bool
    error_step: int | None = Field(default=None, description="Index of the wrong step, if any")
    error_kind: Literal["arithmetic_slip", "wrong_operation", "carried_error"] | None = None


class SpotMistakeContent(Contract):
    puzzles: list[MistakePuzzle] = Field(min_length=1, max_length=8)
