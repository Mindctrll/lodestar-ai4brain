"""Graph tests for WP1.4: golden path with the stub LLM, pause and resume across a restart,
refusals, degradation, and the canary key (AGENTS.md rule 9)."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.runner import SessionRunner
from backend.coach.verify import verify
from backend.contracts.facts import Fact, FactsPacket
from backend.contracts.llm import LlmSelection
from backend.contracts.trial import TrialEvent
from backend.db import tables as t
from backend.db.llm_store import save_credential, set_selection
from backend.db.twin_store import record_trials
from backend.llm.vault import Vault
from tests.backend.agent.conftest import MASTER_KEY, RunnerFactory, new_user


async def collect(
    runner: SessionRunner, user_id: UUID, session_id: UUID, **kw: Any
) -> list[dict[str, Any]]:
    return [e async for e in runner.run(user_id, session_id, **kw)]


def interrupt_of(events: list[dict[str, Any]]) -> dict[str, Any]:
    [event] = [e for e in events if e["kind"] == "interrupt"]
    spec: dict[str, Any] = event["payload"]["spec"]
    return spec


async def play(
    runner: SessionRunner, engine: AsyncEngine, user_id: UUID, session_id: UUID,
    spec: dict[str, Any], results: list[bool],
) -> list[dict[str, Any]]:  # fmt: skip
    """What the browser does: stream trials to /events, then resume the graph."""
    round_id = UUID(spec["round_id"])
    start = datetime.now(UTC)
    trials = [
        TrialEvent(
            trial_id=uuid4(), round_id=round_id, session_id=session_id, game_id=spec["game_id"],
            level=spec["level"], trial_index=i, stimulus={}, correct=c, rt_ms=600.0,
            ts=start + timedelta(seconds=4 * i),
        )
        for i, c in enumerate(results)
    ]  # fmt: skip
    async with engine.begin() as conn:
        await record_trials(conn, user_id, trials)
    result = {
        "round_id": str(round_id), "game_id": spec["game_id"], "status": "completed",
        "trial_count": len(results), "final_level": spec["level"],
        "started_at": start.isoformat(), "ended_at": (start + timedelta(minutes=1)).isoformat(),
    }  # fmt: skip
    return await collect(runner, user_id, session_id, resume=result)


async def test_full_session_with_the_stub_llm(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    """start -> play (pause) -> resume -> coach -> remember, three rounds, then consolidate."""
    runner = await make_runner()
    user_id = await new_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id)
    decisions = [e for e in events if e["kind"] == "decision"]
    assert decisions and decisions[0]["node"] == "plan_next" and decisions[0]["reason"]
    spec = interrupt_of(events)
    assert spec["mode"] == "assess"  # nothing known yet: measure first
    nodes_done = {e["node"] for e in events if e["kind"] == "node" and e["status"] == "done"}
    assert {"load_twin", "recall_memory", "read_affect", "read_context", "forecast"} <= nodes_done

    for round_no in range(3):
        events = await play(runner, aengine, user_id, session_id, spec, [True] * 9 + [False] * 3)
        says = [e["text"] for e in events if e["kind"] == "say"]
        assert says, "every round gets an after-game message"
        assert any("[F" in s for s in says)  # cites facts
        if round_no < 2:
            spec = interrupt_of(events)
    assert any(e["kind"] == "session" and e["status"] == "ended" for e in events)
    assert events[-1] == {"kind": "done", "waiting": False}

    async with aengine.connect() as conn:
        state = t.dimension_state
        n_dims = (await conn.execute(
            select(func.count()).select_from(state).where(state.c.user_id == user_id)
        )).scalar_one()  # fmt: skip
        reasons = (await conn.execute(
            select(t.decisions.c.reason).where(t.decisions.c.session_id == session_id)
        )).scalars().all()  # fmt: skip
        status = (await conn.execute(
            select(t.sessions.c.status).where(t.sessions.c.session_id == session_id)
        )).scalar_one()  # fmt: skip
    assert n_dims >= 3 and all(reasons) and len(reasons) == 6 and status == "ended"


async def test_paused_session_survives_a_server_restart(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    first = await make_runner()
    user_id = await new_user(aengine)
    session_id = await first.create_session(user_id, "ui")
    spec = interrupt_of(await collect(first, user_id, session_id))

    second = await make_runner()  # a new process: new pool, new compiled graph, same database
    pending = await second.pending(user_id, session_id)
    assert pending is not None and pending["payload"]["spec"]["round_id"] == spec["round_id"]
    events = await play(second, aengine, user_id, session_id, spec, [True] * 10)
    assert any(e["kind"] == "say" for e in events)


async def test_duplicate_resume_scores_once(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await new_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    await play(runner, aengine, user_id, session_id, spec, [True] * 10)
    async with aengine.connect() as conn:
        updates = (await conn.execute(text(
            "SELECT count(*) FROM twin.events WHERE user_id = :u AND type = 'twin.updated'"
        ), {"u": user_id})).scalar_one()  # fmt: skip
    assert updates == 1


async def test_diagnosis_request_gets_the_fixed_reply(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    calls: list[int] = []

    def responder(messages: Any) -> str:
        calls.append(1)
        return "x"

    runner = await make_runner(responder=responder)
    user_id = await new_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(
        runner, user_id, session_id, message="Do I have ADHD? My focus scores are low."
    )
    [say] = [e for e in events if e["kind"] == "say"]
    assert say["template"] == "diagnosis" and "doctor or psychologist" in say["text"]
    assert "ADHD" not in say["text"] and not calls  # no LLM free text for this reply


async def test_llm_down_falls_back_to_a_template(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    def broken(messages: Any) -> str:
        raise RuntimeError("model down")

    runner = await make_runner(responder=broken)
    user_id = await new_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id))
    events = await play(runner, aengine, user_id, session_id, spec, [True] * 8 + [False] * 2)
    assert any(e["kind"] == "degraded" and e["to"] == "template" for e in events)
    says = " ".join(e["text"] for e in events if e["kind"] == "say")
    assert "[F" in says  # the template is built from facts


async def test_canary_key_never_leaks(
    make_runner: RunnerFactory, aengine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """AGENTS.md rule 9: a saved key must not show up in logs, traces, checkpoints or events."""
    canary = f"sk-canary-{uuid4().hex}"
    runner = await make_runner(base_overrides={"openai": "http://127.0.0.1:9/v1"})
    user_id = await new_user(aengine)
    async with aengine.begin() as conn:
        sealed = Vault(MASTER_KEY).seal(user_id, "openai", canary)
        await save_credential(conn, user_id, "openai", sealed, "ok")
        await set_selection(
            conn, user_id, LlmSelection(mode="hosted", provider="openai", model="m")
        )
    with caplog.at_level(logging.DEBUG):
        session_id = await runner.create_session(user_id, "ui")
        spec = interrupt_of(await collect(runner, user_id, session_id))
        events = await play(runner, aengine, user_id, session_id, spec, [True] * 10)
    assert any(e["kind"] == "degraded" for e in events)  # the fake endpoint is unreachable
    assert canary not in caplog.text and canary not in str(events)
    async with aengine.connect() as conn:
        for query in (
            "SELECT payload::text FROM twin.events WHERE user_id = :u",
            "SELECT coalesce(payload::text, '') FROM agent.traces WHERE user_id = :u",
            "SELECT candidates::text || reason FROM agent.decisions WHERE user_id = :u",
            "SELECT checkpoint::text FROM checkpoints WHERE thread_id = :s",
            "SELECT encode(blob, 'escape') FROM checkpoint_blobs"
            " WHERE thread_id = :s AND blob IS NOT NULL",
            "SELECT encode(blob, 'escape') FROM checkpoint_writes WHERE thread_id = :s",
        ):
            rows = (
                (await conn.execute(text(query), {"u": user_id, "s": str(session_id)}))
                .scalars()
                .all()
            )
            assert rows is not None
            assert all(canary not in (r or "") for r in rows), query


def test_verifier_catches_wrong_numbers_and_uncited_claims() -> None:
    packet = FactsPacket(
        facts=[Fact(id="F1", text="Working memory estimate 54% (80% range 41-66%)")]
    )
    names = ["Working memory"]
    assert verify("Working memory estimate 54% [F1].", packet, names).ok
    assert not verify("Working memory estimate 60% [F1].", packet, names).ok
    assert not verify("Your working memory is 54%.", packet, names).ok
    assert not verify("Nice [F9].", packet, names).ok
    assert not verify("No deficit here [F1].", packet, names).ok
    # A citation after the punctuation belongs to the sentence before it.
    assert verify("Working memory estimate 54%! [F1] Keep going.", packet, names).ok
