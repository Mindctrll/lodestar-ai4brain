"""WP4.4 extensibility drill: a skill added with only YAML and one browser plugin (Rhythm and
timing, played in Off Beat) is picked by the policy, scored, and shown in the Brain Twin."""

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.api.main import app
from backend.db import tables as t
from backend.db.twin_store import read_twin
from tests.backend.agent.conftest import RunnerFactory
from tests.backend.agent.test_graph import play
from tests.backend.agent.test_policy import REGISTRY, decisions, returning_user, start


def test_the_new_skill_is_in_the_registry_the_browser_reads() -> None:
    body = TestClient(app).get("/registry").json()
    timing = next(d for d in body["dimensions"] if d["id"] == "timing")
    assert timing["badge"] == "experimental" and not timing["in_overall"]
    assert REGISTRY.game("off_beat").primary_dims == ["timing"]


async def test_new_skill_is_picked_scored_and_shown(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    user_id = await returning_user(aengine)  # every skill in the pool known, sigma 0.5
    async with aengine.begin() as conn:  # ...except the new one, never played
        await conn.execute(
            delete(t.dimension_state).where(
                t.dimension_state.c.user_id == user_id, t.dimension_state.c.dim == "timing"
            )
        )

    # Policy: the least known skill wins, and the reason says why.
    session_id, spec = await start(runner, user_id)
    assert spec["game_id"] == "off_beat"
    [(chosen, reason)] = await decisions(aengine, session_id, "plan_next")
    assert chosen == "timing:off_beat"
    assert reason == "Rhythm and timing is a skill I haven't measured yet."
    assert set(spec["knobs"]) == {"shift_pct", "beats"}

    # Scoring: one round moves the new skill's estimate and narrows its range.
    await play(runner, aengine, user_id, session_id, spec, [True] * 10 + [False] * 2)
    async with aengine.connect() as conn:
        twin = await read_twin(conn, user_id)
    timing = next(d for d in twin.dims if d.dim == "timing")
    assert timing.n > 0 and timing.mu > 0.0 and timing.sigma < 1.0
    assert timing.percent_low < timing.percent < timing.percent_high  # shown as a range
