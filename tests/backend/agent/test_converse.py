"""WP2.11 conversation: intent routing on 100 labelled utterances, the safety gate, the converse
tools (every write pauses for a yes first), and the workflows UW3, UW7, UW9, UW11, UW13, UW20."""

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml
from langchain_core.messages import BaseMessage
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.intents import ROUTER_PROMPT, classify
from backend.agent.nodes.gate import REPLIES, SAFETY_PROMPT, screen
from backend.agent.slots import due_date, history_days, life_event, local_tz
from backend.agent.tools import TOOLS
from backend.coach.language import find_banned
from backend.coach.verify import verify
from backend.contracts.facts import FactsPacket
from backend.db import tables as t
from backend.llm.stub import default_responder
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import RunnerFactory, new_user
from tests.backend.agent.test_graph import collect, interrupt_of, play
from tests.backend.agent.test_policy import returning_user

HERE = Path(__file__).parent
REGISTRY = load_registry()
NAMES = [d.name for d in REGISTRY.dimensions]
LABELLED = yaml.safe_load((HERE / "intents.yaml").read_text())
SAFETY = yaml.safe_load((HERE / "safety.yaml").read_text())


def asked(events: list[dict[str, Any]]) -> dict[str, Any]:
    [event] = [e for e in events if e["kind"] == "interrupt"]
    payload: dict[str, Any] = event["payload"]
    return payload


def said(events: list[dict[str, Any]]) -> str:
    return " ".join(e["text"] for e in events if e["kind"] == "say")


async def count(engine: AsyncEngine, table: Any, user_id: UUID) -> int:
    async with engine.connect() as conn:
        n: int = (
            await conn.execute(
                select(func.count()).select_from(table).where(table.c.user_id == user_id)
            )
        ).scalar_one()
    return n


async def event_types(engine: AsyncEngine, user_id: UUID) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(t.events.c.type).where(t.events.c.user_id == user_id).order_by(t.events.c.ts)
        )
        return [r.type for r in rows]


# Routing and the safety gate ------------------------------------------------------------------


def test_intents_on_100_labelled_utterances() -> None:
    assert len(LABELLED) == 100
    wrong = []
    for item in LABELLED:
        intent = classify(item["text"], "ui", REGISTRY).intent
        checks = {
            "kind": (intent.kind, item["kind"]),
            "game": (intent.game_id, item.get("game", intent.game_id)),
            "dim": (intent.dim, item.get("dim", intent.dim)),
            "avoid": (sorted(intent.avoid_dims), sorted(item.get("avoid", []))),
        }
        if item["kind"] == "play":
            checks["quick"] = (intent.quick, item.get("quick", False))
        if item["kind"] == "chat":
            checks["tool"] = (intent.tool, item.get("tool"))
        bad = {k: got for k, (got, want) in checks.items() if got != want}
        if bad:
            wrong.append((item["text"], bad))
    assert len(wrong) <= 5, wrong  # at least 95% right on kind and every slot


def _right(item: dict[str, Any], intent: Any) -> bool:
    if intent.kind != item["kind"]:
        return False
    if item.get("game") and intent.game_id != item["game"]:
        return False
    if item.get("dim") and intent.dim != item["dim"]:
        return False
    if sorted(intent.avoid_dims) != sorted(item.get("avoid", [])):
        return False
    return item["kind"] != "chat" or intent.tool == item.get("tool")


HELDOUT = yaml.safe_load((HERE / "intents_heldout.yaml").read_text())


def test_heldout_utterances_rules_are_rarely_sure_and_wrong() -> None:
    """Phrasings written after the rules and never used to tune them. The rules alone get most of
    them; when they don't, they should say they aren't sure, so the model router gets the turn."""
    right = sure_wrong = 0
    for item in HELDOUT:
        routed = classify(item["text"], "ui", REGISTRY)
        if _right(item, routed.intent):
            right += 1
        elif routed.sure:
            sure_wrong += 1
    print(f"held out, rules only: {right}/{len(HELDOUT)} right, {sure_wrong} sure and wrong")
    assert right >= 0.7 * len(HELDOUT) and sure_wrong <= 0.1 * len(HELDOUT)


@pytest.mark.skipif(
    not __import__("os").environ.get("LODESTAR_OLLAMA_TESTS"),
    reason="needs a local Ollama; set LODESTAR_OLLAMA_TESTS=1 (slow on CPU)",
)
async def test_local_model_router_on_unsure_turns(aengine: AsyncEngine) -> None:
    """The full router (rules, then the local model when unsure) on both sets."""
    import os

    from backend.agent.intents import route
    from backend.contracts.llm import LlmSelection
    from backend.llm.factory import LlmFactory
    from tests.backend.agent.conftest import test_settings

    settings = test_settings(ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    llm = LlmFactory(REGISTRY, settings, aengine)
    local = LlmSelection(mode="local", provider="ollama", model=settings.local_model)
    user_id = await new_user(aengine, mode="local")
    for name, items in (("labelled", LABELLED), ("held out", HELDOUT)):
        right = asked_model = 0
        for item in items:
            intent, _ = await route(item["text"], "ui", REGISTRY, llm, user_id, local)
            right += _right(item, intent)
            asked_model += intent.source == "llm"
        print(f"{name}: {right}/{len(items)} right, model asked {asked_model} times")
        assert right >= 0.8 * len(items)


@pytest.mark.parametrize("kind", ["diagnosis", "medical", "crisis", "safe"])
def test_safety_rules(kind: str) -> None:
    want = None if kind == "safe" else kind
    missed = [line for line in SAFETY[kind] if screen(line) != want]
    assert missed == []
    assert len(SAFETY["diagnosis"]) == 30
    for reply in REPLIES.values():
        assert find_banned(reply) == []


def test_slots() -> None:
    today = datetime(2026, 10, 21).date()  # a Wednesday
    assert due_date("by 3 Nov", today) == datetime(2026, 11, 3).date()
    assert due_date("aim for better maths by 15 November", today) == datetime(2026, 11, 15).date()
    assert due_date("in 2 weeks", today) == datetime(2026, 11, 4).date()
    assert due_date("by friday", today) == datetime(2026, 10, 23).date()
    exams = datetime(2026, 10, 30).date()
    assert due_date("solid before exams", today, exams) == exams
    assert due_date("whenever", today) == datetime(2026, 11, 4).date()
    assert history_days("over the last month") == 30 and history_days("past 3 weeks") == 21
    tz = local_tz("Africa/Tunis")
    now = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)
    slept = life_event("I slept like 4 hours.", now, tz)
    assert slept is not None and slept.label == "slept badly" and slept.light
    assert (slept.end - slept.start).total_seconds() == 86_400
    assert slept.start.astimezone(tz).hour == 0  # the user's own day
    week = life_event("I have exams all week", now, tz)
    assert week is not None and week.label == "exam period"
    assert week.end.astimezone(tz).date() == datetime(2026, 10, 26).date()  # through Sunday
    assert life_event("let's play", now, tz) is None


def routing_responder(router: dict[str, Any], safety: str = "none") -> Any:
    """A stub model that answers the router and the safety check, and drafts like the default."""

    def respond(messages: Sequence[BaseMessage]) -> str:
        system = str(messages[0].content)
        if system == ROUTER_PROMPT:
            return json.dumps(router)
        if system == SAFETY_PROMPT:
            return json.dumps({"kind": safety})
        return default_responder(messages)

    return respond


async def test_router_asks_a_model_only_when_the_rules_arent_sure(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner(
        routing_responder({"kind": "play", "skill": "spatial", "game": None, "quick": False})
    )
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id, message="hmm, shapes maybe"))
    assert "spatial_thinking" in REGISTRY.game(spec["game_id"]).dims  # the model's reading
    # A clear request never waits on the model: the stub would have said "play" here too.
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id, message="what can you do?")
    assert "practice coach" in said(events)


async def test_safety_model_can_add_a_refusal_but_rules_come_first(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner(routing_responder({"kind": "chat"}, safety="crisis"))
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id, message="I feel so alone and hopeless")
    assert said(events) == REPLIES["crisis"]
    # A rule hit is final whatever the model says.
    lenient = await make_runner(routing_responder({"kind": "chat"}, safety="none"))
    session_id = await lenient.create_session(user_id, "ui")
    events = await collect(lenient, user_id, session_id, message="Do I have ADHD?")
    assert said(events) == REPLIES["diagnosis"]


async def test_uw13_thirty_diagnosis_requests_through_the_graph(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    conditions = re.compile(r"adhd|autis|dyslex|dementia|alzheimer|bipolar|ocd|depress", re.I)
    for ask in SAFETY["diagnosis"]:
        session_id = await runner.create_session(user_id, "ui")
        events = await collect(runner, user_id, session_id, message=ask)
        reply = said(events)
        assert reply == REPLIES["diagnosis"], ask
        assert not conditions.search(reply)
        assert not any(e["kind"] == "interrupt" for e in events)  # no game, no tool


# Tools that write always pause ----------------------------------------------------------------

WRITES = [
    ("I want my memory to be solid before exams.", "set_goal", t.goals),
    ("I slept like 4 hours.", "log_life_context", t.life_context),
    ("stop suggesting maths this week", "update_settings", t.skill_pauses),
    ("I want to run an experiment", "start_experiment", t.experiments),
]


def test_every_writing_tool_is_behind_a_confirmation() -> None:
    writing = {name for name, spec in TOOLS.items() if spec.writes}
    assert writing == {"set_goal", "log_life_context", "update_settings", "start_experiment"}
    assert {name for _, name, _ in WRITES} == writing


@pytest.mark.parametrize(("text", "tool", "table"), WRITES)
async def test_tools_that_write_pause_for_a_yes(
    make_runner: RunnerFactory, aengine: AsyncEngine, text: str, tool: str, table: Any
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    before = await event_types(aengine, user_id)
    session_id = await runner.create_session(user_id, "ui")
    payload = asked(await collect(runner, user_id, session_id, message=text))
    assert payload["type"] == "confirm" and payload["tool"] == tool
    prompt = payload["prompt"]
    assert prompt.endswith("?") and find_banned(prompt) == []
    packet = FactsPacket.model_validate(payload["facts"])
    assert verify(prompt, packet, NAMES, "willow").ok, prompt  # numbers come from facts
    assert await count(aengine, table, user_id) == 0  # nothing written while waiting

    # "No" leaves everything as it was.
    events = await collect(runner, user_id, session_id, resume={"confirmed": False})
    assert "left it as it was" in said(events)
    assert await count(aengine, table, user_id) == 0
    assert len(await event_types(aengine, user_id)) == len(before) + 1  # session.started only

    # Asked again and confirmed: written once, with its event.
    session_id = await runner.create_session(user_id, "ui")
    asked(await collect(runner, user_id, session_id, message=text))
    events = await collect(runner, user_id, session_id, resume={"confirmed": True})
    assert await count(aengine, table, user_id) == 1
    expected = {
        "set_goal": "goal.set",
        "log_life_context": "context.added",
        "start_experiment": "experiment.started",
    }.get(tool, "settings.changed")
    assert expected in await event_types(aengine, user_id)
    assert verify(said(events), packet, NAMES, "willow").ok


# Workflows ------------------------------------------------------------------------------------


async def test_uw9_life_context_weighs_rounds_half(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    """Inside the window each answer counts as half the evidence (weight 0.5). In the Kalman
    update that moves the mean about 60% as far as outside it, and the range shrinks less."""
    runner = await make_runner()

    async def speed_change(tell: bool) -> float:
        async with aengine.begin() as conn:  # learned item difficulty is shared: same start
            await conn.execute(delete(t.item_difficulty))
        user_id = await returning_user(aengine)
        session_id = await runner.create_session(user_id, "ui")
        if tell:
            asked(await collect(runner, user_id, session_id, message="I slept like 4 hours."))
            events = await collect(runner, user_id, session_id, resume={"confirmed": True})
            assert said(events) == (
                "Thanks for telling me. I'll keep today light, and today's results will count "
                "less toward your profile."
            )
        spec = interrupt_of(await collect(runner, user_id, session_id, message="play Quick Draw"))
        await play(runner, aengine, user_id, session_id, spec, [True, False] * 5)
        async with aengine.connect() as conn:
            mu = (
                await conn.execute(
                    select(t.dimension_state.c.mu).where(
                        t.dimension_state.c.user_id == user_id,
                        t.dimension_state.c.dim == "processing_speed",
                    )
                )
            ).scalar_one()
        return float(mu)

    outside, inside = await speed_change(False), await speed_change(True)
    assert outside != 0.0
    assert 0.45 <= inside / outside <= 0.65, (inside, outside)


async def test_uw11_goal_then_progress(make_runner: RunnerFactory, aengine: AsyncEngine) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    payload = asked(
        await collect(
            runner, user_id, session_id, message="I want my memory to be solid before exams."
        )
    )
    assert re.search(r"within ±\d+ points by \d+ \w{3}", payload["prompt"])
    assert re.search(r"about \d+ more working memory rounds", payload["prompt"])
    await collect(runner, user_id, session_id, resume={"confirmed": True})
    # The next pick favours the goal skill, and says so in its breakdown.
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    assert "working_memory" in REGISTRY.game(spec["game_id"]).primary_dims
    async with aengine.connect() as conn:
        candidates = (
            await conn.execute(
                select(t.decisions.c.candidates).where(
                    t.decisions.c.session_id == session_id, t.decisions.c.node == "plan_next"
                )
            )
        ).scalar_one()
    top = candidates[0]
    assert top["option"] == "working_memory" and top["breakdown"]["goal_weight"] == 1.0


async def test_uw7_explain_cites_the_latest_decision(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    interrupt_of(await collect(runner, user_id, session_id))
    events = await collect(runner, user_id, session_id, message="Why memory again?")
    async with aengine.connect() as conn:
        row = (
            await conn.execute(
                select(t.decisions)
                .where(t.decisions.c.user_id == user_id, t.decisions.c.node == "plan_next")
                .order_by(t.decisions.c.ts.desc())
                .limit(1)
            )
        ).one()
    says = [e for e in events if e["kind"] == "say"]
    assert any(e.get("refs", {}).get("D1") == str(row.decision_id) for e in says)
    reply = said(events)
    allowed = " ".join([row.reason, *(json.dumps(c) for c in row.candidates)])
    for number in re.findall(r"\d+(?:\.\d+)?", reply.replace("[D1]", "")):
        if not re.fullmatch(r"F?\d", number):
            assert number in allowed, (number, reply)


async def test_uw7_without_a_good_draft_the_reason_is_still_cited(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner(lambda messages: "You did 99% better than everyone.")
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    interrupt_of(await collect(runner, user_id, session_id))
    events = await collect(runner, user_id, session_id, message="why this game?")
    says = [e for e in events if e["kind"] == "say"]
    assert "99%" not in said(events)  # the unverified draft never reaches the user
    assert any("D1" in e.get("refs", {}) for e in says)


async def test_uw3_decline_then_nudge_once(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    nudges = []
    for session in range(4):
        session_id = await runner.create_session(user_id, "ui")
        events = await collect(
            runner, user_id, session_id, message="Not memory today, something quick."
        )
        spec = interrupt_of(events)
        game = REGISTRY.game(spec["game_id"])
        assert "working_memory" not in game.primary_dims and game.duration_s <= 60
        plan = [e for e in events if e["kind"] == "decision" and e["node"] == "plan_next"]
        assert plan[0]["reason"].startswith("Sure. Here's")
        nudged = any(e["kind"] == "say" and "skipped" in e["text"] for e in events)
        nudges.append(nudged)
        if nudged:  # "Stop suggesting it" answers the nudge: memory pauses for a week.
            payload = asked(
                await collect(runner, user_id, session_id, message="stop suggesting it this week")
            )
            assert payload["type"] == "confirm" and "working memory" in payload["prompt"]
            await collect(runner, user_id, session_id, resume={"confirmed": True})
        if session == 0:  # the rest of that session leaves memory alone too
            for _ in range(2):
                events = await play(runner, aengine, user_id, session_id, spec, [True] * 10)
                if not any(e["kind"] == "interrupt" for e in events):
                    break
                spec = interrupt_of(events)
                assert "working_memory" not in REGISTRY.game(spec["game_id"]).primary_dims
    assert nudges == [False, False, True, False]  # once, after the third session
    assert await count(aengine, t.skill_pauses, user_id) == 1
    session_id = await runner.create_session(user_id, "ui")  # paused, even without asking
    spec = interrupt_of(await collect(runner, user_id, session_id))
    assert "working_memory" not in REGISTRY.game(spec["game_id"]).primary_dims


async def test_new_message_replaces_the_waiting_game(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    first = interrupt_of(await collect(runner, user_id, session_id))
    second = interrupt_of(
        await collect(runner, user_id, session_id, message="not that one, give me something else")
    )
    assert second["game_id"] != first["game_id"]
    async with aengine.connect() as conn:
        status = (
            await conn.execute(
                select(t.rounds.c.status).where(t.rounds.c.round_id == UUID(first["round_id"]))
            )
        ).scalar_one()
    assert status == "abandoned"


async def test_a_question_keeps_the_waiting_game(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    first = interrupt_of(await collect(runner, user_id, session_id))
    for text in ("why this game?", "Do I have ADHD?", "I slept badly"):
        events = await collect(runner, user_id, session_id, message=text)
        if asked(events)["type"] == "confirm":
            events = await collect(runner, user_id, session_id, resume={"confirmed": False})
        assert interrupt_of(events)["round_id"] == first["round_id"], text  # same game waits
    await play(runner, aengine, user_id, session_id, first, [True] * 10)
    async with aengine.connect() as conn:
        status = (
            await conn.execute(
                select(t.rounds.c.status).where(t.rounds.c.round_id == UUID(first["round_id"]))
            )
        ).scalar_one()
    assert status == "completed"


async def test_uw20_switch_coach_and_mode(make_runner: RunnerFactory, aengine: AsyncEngine) -> None:
    runner = await make_runner()
    user_id = await new_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    payload = asked(await collect(runner, user_id, session_id, message="switch to Spark"))
    assert "Spark" in payload["prompt"]
    events = await collect(runner, user_id, session_id, resume={"confirmed": True})
    assert "Your coach is now Spark." in said(events)
    payload = asked(await collect(runner, user_id, session_id, message="put me on push mode"))
    assert "65% success" in payload["prompt"]
    await collect(runner, user_id, session_id, resume={"confirmed": True})
    async with aengine.connect() as conn:
        row = (
            await conn.execute(
                select(t.users.c.persona, t.users.c.success_mode).where(
                    t.users.c.user_id == user_id
                )
            )
        ).one()
    assert (row.persona, row.success_mode) == ("spark", "push")


async def test_read_tools_answer_from_facts(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)
    for text in ("How am I doing?", "what's my memory score", "show my progress this week"):
        session_id = await runner.create_session(user_id, "ui")
        events = await collect(runner, user_id, session_id, message=text)
        reply = said(events)
        assert reply and find_banned(reply) == []
        assert not any(e["kind"] == "interrupt" for e in events)  # reading never pauses
