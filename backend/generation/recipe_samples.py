"""WP3.7 "Done when": 50 LLM-written recipes; every valid one runs, every invalid one is rejected.

    uv run python -m backend.generation.recipe_samples            # deterministic fixture set
    uv run python -m backend.generation.recipe_samples --local    # ask the local Ollama model
    uv run python -m backend.generation.recipe_samples --user <id> --provider <p> --model <m>

writes `tests/fixtures/custom_recipes.yaml`: each request, the recipe as written, and the
validator's verdict. `tests/backend/generation/test_custom_blocks.py` re-checks every verdict and
`frontend/src/games/custom_blocks/engine.test.ts` builds and plays every valid recipe.

Without a model, the fixture set mimics LLM output: mostly sensible recipes, plus the mistakes
models make (unknown blocks, code, prose around the JSON, impossible timings, answers that are
not among the options...), each labelled with how it was broken.
"""

import argparse
import asyncio
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from langchain_core.messages import HumanMessage, SystemMessage

from backend.generation.blocks import validate_recipe
from backend.generation.generators.custom_blocks import ability_dims

FIXTURE = Path("tests/fixtures/custom_recipes.yaml")
SEED = 37

REQUESTS = [
    "a game where I remember a phone number while doing maths",
    "something to make me faster at reacting",
    "a game with shapes I have to remember",
    "quiz me on easy capital cities",
    "a game where the rules keep changing",
    "remember a shopping list while I'm distracted",
    "a quick focus game with stars",
    "test how many letters I can hold in my head",
    "a game about odd and even numbers",
    "something with words to remember",
    "make me press only for the red circle",
    "a memory game that gets me tapping in between",
    "a trivia round about the sea",
    "a game to practise switching between two rules",
    "show me digits and ask for them back",
    "a game about spotting the target fast",
    "help me practise holding back",
    "a short game with a countdown and a recall",
    "a game where I remember a sequence of fruit",
    "make a game where I sort numbers high or low",
    "a game for my working memory with a twist",
    "quiz me about the planets",
    "a game where I remember symbols",
    "a fast reaction game with lots of decoys",
    "remember five words then do maths",
    "a game for flexible thinking",
    "a recognition game with words",
    "a reaction game with arrows",
    "a game where I recall letters in order",
    "make me a mixed game: memory then speed",
    "a game where I remember a code",
    "a calm game with a timer and a question",
    "a game about remembering colours",
    "something like a pub quiz on football",
    "a game for attention with decoy letters",
    "a game where I remember a bus number",
    "a game with a rule that flips every few turns",
    "three questions about animals",
    "remember a list of tools",
    "a reaction game where I only press for the moon",
    "a game to remember shapes and pick the ones I saw",
    "a long memory challenge",
    "digits forwards with a maths break",
    "a game about Tunisian food words",
    "make it hard: lots of letters fast",
    "a short game for my morning",
    "a sorting game with odd numbers",
    "a reaction game with emojis",
    "memorise a list of cities in order",
    "a game where I tap between memorising",
]

WORDS = ["olive", "lemon", "bread", "honey", "mint", "salt", "date", "fig", "rice", "tea", "nut"]
SYMBOLS = ["★", "●", "■", "▲", "◆", "☾", "X", "O", "→", "←"]
QUIZ = [
    ("Which is a planet?", ["Mars", "Moon", "Sun"], "Mars"),
    ("Which number is even?", ["3", "8", "11"], "8"),
    ("Which animal lives in the sea?", ["Camel", "Octopus", "Fox"], "Octopus"),
    ("What is the capital of Tunisia?", ["Sfax", "Tunis", "Sousse"], "Tunis"),
    ("How many sides has a triangle?", ["3", "4", "5"], "3"),
    ("Which is a fruit?", ["Carrot", "Apple", "Onion"], "Apple"),
]


@dataclass(frozen=True)
class Sample:
    request: str
    recipe: Any  # as written: a mapping, or text when the model answered with prose
    broken: str | None  # fixture set only: how it was broken on purpose


def _memory(rng: random.Random) -> dict[str, Any]:
    kind = rng.choice(["digits", "letters", "words", "shapes", "list"])
    n = rng.randint(3, 4 if kind == "shapes" else 7)
    items: Any = rng.sample(WORDS, n) if kind == "list" else f"{kind}:{n}"
    recall = (
        "ordered" if kind in ("digits", "list") else rng.choice(["free", "ordered", "recognition"])
    )
    steps: list[dict[str, Any]] = [
        {"block": "show_items", "items": items, "ms_each": rng.choice([600, 800, 1000, 1200])}
    ]
    if rng.random() < 0.7:
        task = rng.choice(["arithmetic:easy", "arithmetic:hard", "tapping"])
        steps.append({"block": "distractor", "task": task, "seconds": rng.randint(5, 15)})
    else:
        steps.append({"block": "timer", "seconds": rng.randint(2, 6)})
    steps.append({"block": "recall", "kind": recall})
    dim = (
        "working_memory"
        if len(steps) == 3 and steps[1]["block"] == "distractor"
        else "short_term_memory"
    )
    return {
        "title": "Hold That Thought",
        "dims": {dim: 1.0},
        "steps": steps,
        "repeat": rng.randint(1, 3),
    }


def _speed(rng: random.Random) -> dict[str, Any]:
    target, *decoys = rng.sample(SYMBOLS, rng.randint(1, 4))
    react = {
        "block": "react",
        "target": target,
        "distractors": decoys,
        "deadline_ms": rng.choice([700, 900, 1200]),
        "trials": rng.randint(8, 20),
    }
    dims = {"processing_speed": 1.0, "inhibition": 0.4} if decoys else {"processing_speed": 1.0}
    return {
        "title": "Catch It",
        "dims": dims,
        "steps": [react, {"block": "feedback", "level": "brief"}],
        "repeat": rng.randint(1, 2),
    }


def _rules(rng: random.Random) -> dict[str, Any]:
    trials = rng.randint(8, 16)
    rule = {"block": "rule", "rule": rng.choice(["odd_even", "high_low"]), "trials": trials}
    if rng.random() < 0.7:
        rule["switch_after"] = rng.randint(2, trials - 1)
    return {
        "title": "Flip the Rule",
        "dims": {"cognitive_flexibility": 1.0},
        "steps": [rule, {"block": "feedback", "level": "full"}],
    }


def _quiz(rng: random.Random) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [{"block": "timer", "seconds": 3}]
    for question, options, answer in rng.sample(QUIZ, rng.randint(2, 4)):
        steps.append(
            {"block": "choice", "question": question, "options": options, "answer": answer}
        )
    return {"title": "Quick Quiz", "dims": {"reasoning": 1.0}, "steps": steps}


def _broken(kind: str, recipe: dict[str, Any], rng: random.Random) -> Any:
    steps = recipe["steps"]
    match kind:
        case "unknown_block":
            steps.append({"block": "draw_picture", "seconds": 10})
        case "writes_code":
            steps[0]["code"] = "document.body.innerHTML = ''"
        case "prose_around_json":
            return "Sure! Here is a fun game for you:\n" + json.dumps(recipe) + "\nEnjoy!"
        case "too_long":
            recipe["repeat"] = 5
            steps.insert(0, {"block": "distractor", "task": "tapping", "seconds": 60})
        case "too_fast":
            steps.insert(0, {"block": "show_items", "items": "digits:5", "ms_each": 50})
            steps.append({"block": "recall", "kind": "ordered"})
        case "nothing_scored":
            recipe["steps"] = [
                {"block": "show_items", "items": "words:5", "ms_each": 900},
                {"block": "timer", "seconds": 5},
            ]
        case "recall_first":
            recipe["steps"] = [
                {"block": "recall", "kind": "ordered"},
                {"block": "show_items", "items": "digits:6", "ms_each": 800},
            ]
        case "answer_not_an_option":
            steps.append(
                {
                    "block": "choice",
                    "question": "Which is bigger?",
                    "options": ["2", "5"],
                    "answer": "7",
                }
            )
        case "unknown_skill":
            recipe["dims"] = {"telepathy": 1.0}
        case "no_main_skill":
            recipe["dims"] = {d: 0.5 for d in recipe["dims"]}
        case "clinical_word":
            recipe["title"] = "ADHD Booster"
        case "missing_steps":
            del recipe["steps"]
        case "digits_recognised":
            recipe["steps"] = [
                {"block": "show_items", "items": "digits:7", "ms_each": 700},
                {"block": "recall", "kind": "recognition"},
            ]
        case "too_many_shapes":
            recipe["steps"] = [
                {"block": "show_items", "items": "shapes:12", "ms_each": 700},
                {"block": "recall", "kind": "free"},
            ]
        case "switch_too_late":
            recipe["steps"] = [
                {"block": "rule", "rule": "odd_even", "trials": 6, "switch_after": 9}
            ]
    return recipe


BREAKS = [
    "unknown_block", "writes_code", "prose_around_json", "too_long", "too_fast",
    "nothing_scored", "recall_first", "answer_not_an_option", "unknown_skill", "no_main_skill",
    "clinical_word", "missing_steps", "digits_recognised", "too_many_shapes", "switch_too_late",
]  # fmt: skip


def fixture_samples(n: int = 50, seed: int = SEED) -> list[Sample]:
    """Deterministic stand-in for an LLM: every third-ish answer is broken, cycling through every
    kind of mistake so each one is covered."""
    rng = random.Random(seed)
    makers = [_memory, _speed, _rules, _quiz]
    out: list[Sample] = []
    broken = 0
    for i in range(n):
        recipe = makers[i % len(makers)](rng)
        if i % 5 in (1, 3):
            kind = BREAKS[broken % len(BREAKS)]
            broken += 1
            out.append(Sample(REQUESTS[i % len(REQUESTS)], _broken(kind, recipe, rng), kind))
        else:
            # Models often answer with JSON text rather than an object.
            raw: Any = json.dumps(recipe) if i % 7 == 0 else recipe
            out.append(Sample(REQUESTS[i % len(REQUESTS)], raw, None))
    return out


async def llm_samples(
    n: int, user_id: UUID | None, provider: str | None, model: str | None
) -> list[Sample]:
    """Ask a real model for `n` recipes, raw text kept so broken answers are kept too."""
    from backend.config import get_settings
    from backend.contracts.llm import LlmSelection
    from backend.db.engine import get_async_engine
    from backend.generation.pipeline import load_prompt
    from backend.llm.factory import LlmFactory
    from backend.registry.loader import load_registry

    settings = get_settings()
    engine = get_async_engine()
    llm = LlmFactory(load_registry(), settings, engine)
    if provider and model and user_id:
        selection = LlmSelection(mode="hosted", provider=provider, model=model)
    else:
        selection = LlmSelection(mode="local", provider="ollama", model=settings.local_model)
    _, template = load_prompt("custom_blocks")
    dims = json.dumps(sorted(ability_dims()))
    out: list[Sample] = []
    try:
        for request in (REQUESTS * (n // len(REQUESTS) + 1))[:n]:
            messages = [
                SystemMessage("You design short practice games. Answer with JSON only."),
                HumanMessage(template.format(request=request, dims=dims)),
            ]
            reply = await llm.generate(user_id or UUID(int=0), selection, messages)
            out.append(Sample(request, reply.text, None))
    finally:
        await engine.dispose()
    return out


def render(samples: list[Sample], source: str) -> str:
    dims = ability_dims()
    rows = []
    for s in samples:
        recipe, errors = validate_recipe(s.recipe, dims)
        rows.append(
            {
                "request": s.request,
                "source": source,
                "broken": s.broken,
                "valid": not errors,
                "errors": errors,
                "recipe": s.recipe,
                # What the browser receives as spec.content (defaults filled in).
                "served": recipe.model_dump(mode="json") if recipe else None,
            }
        )
    head = (
        "# Generated by `uv run python -m backend.generation.recipe_samples` (WP3.7): recipes as\n"
        "# written and the validator's verdict. Do not edit by hand.\n"
    )
    return head + yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=100)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--local", action="store_true", help="ask the local Ollama model")
    parser.add_argument("--user", type=UUID, help="use this user's saved key")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--out", type=Path, default=FIXTURE)
    args = parser.parse_args()
    if args.local or args.user:
        samples = asyncio.run(llm_samples(args.n, args.user, args.provider, args.model))
        source = "llm"
    else:
        samples, source = fixture_samples(args.n), "fixture"
    args.out.write_text(render(samples, source), encoding="utf-8")
    valid = sum(1 for s in samples if not validate_recipe(s.recipe, ability_dims())[1])
    print(f"{len(samples)} recipes ({source}): {valid} valid, {len(samples) - valid} rejected")


if __name__ == "__main__":
    main()
