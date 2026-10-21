"""WP3.8: the Detective story serves its chapters in order, logs each one, and ends the story."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.db import tables as t
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import RunnerFactory, new_user
from tests.backend.agent.test_graph import collect, interrupt_of, play


def plan_reason(events: list[dict[str, Any]]) -> str:
    [reason] = [e["reason"] for e in events if e["kind"] == "decision" and e["node"] == "plan_next"]
    return str(reason)


async def test_detective_story_plays_every_chapter_then_ends(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    story = load_registry().game("detective").story
    assert story is not None
    runner = await make_runner()
    user_id = await new_user(aengine)
    session_id = await runner.create_session(user_id, "ui")
    events = await collect(runner, user_id, session_id, message="play the Detective story")
    assert plan_reason(events).startswith(story.intro)

    for i, chapter in enumerate(story.chapters, start=1):
        spec = interrupt_of(events)
        assert spec["game_id"] == chapter.game
        assert f"chapter {i} of {len(story.chapters)}: {chapter.title}" in spec["reason"]
        events = await play(runner, aengine, user_id, session_id, spec, [True] * 8 + [False] * 2)
        says = [e["text"] for e in events if e["kind"] == "say" and e["node"] == "story"]
        assert says == ([story.ending] if i == len(story.chapters) else [])

    async with aengine.connect() as conn:
        logged = (
            await conn.execute(
                select(t.events.c.payload)
                .where(t.events.c.session_id == session_id)
                .where(t.events.c.type == "story.chapter_completed")
                .order_by(t.events.c.ts)
            )
        ).scalars().all()  # fmt: skip
        scored = (
            await conn.execute(
                select(t.rounds.c.game_id)
                .where(t.rounds.c.session_id == session_id, t.rounds.c.score.is_not(None))
                .order_by(t.rounds.c.started_at)
            )
        ).scalars().all()  # fmt: skip
    assert [p["chapter"] for p in logged] == [1, 2, 3]
    assert list(scored) == [c.game for c in story.chapters]  # each chapter scored as its game
