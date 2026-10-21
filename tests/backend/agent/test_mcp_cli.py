"""WP3.6: the MCP tool server and the `najma` CLI (UW19).

The CLI's commands run against the real FastAPI app in this process (MCP over HTTP through an
ASGI transport), with the user's input scripted; the last test runs the real `najma` command
against a real server process.
"""

import asyncio
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from datetime import date
from io import StringIO
from typing import Any
from uuid import UUID

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from rich.console import Console
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.tools import TOOLS
from backend.api.deps import engine_dep
from backend.api.main import create_app
from backend.db import tables as t
from backend.db.twin_store import hash_token
from backend.mcp_server.server import NOT_SIGNED_IN
from backend.registry.loader import load_registry
from cli import games, main
from cli.client import Io, call, connect
from cli.render import pct
from cli.session import Chat
from tests.backend.agent.conftest import RunnerFactory, new_user
from tests.backend.agent.test_policy import returning_user

LOCAL = "http://localhost:8000"  # the MCP server only answers to local host names (DNS rebinding)
WEB = "http://localhost:5173"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@pytest.fixture
async def app(make_runner: RunnerFactory, aengine: AsyncEngine) -> AsyncIterator[FastAPI]:
    runner = await make_runner()
    api = create_app(with_lifespan=False)
    api.state.runner = runner
    api.state.services = runner.services
    api.dependency_overrides[engine_dep] = lambda: aengine
    ready, done = asyncio.Event(), asyncio.Event()

    async def serve() -> None:  # in its own task: the manager's scope can't span fixture tasks
        async with api.state.mcp.session_manager.run():
            ready.set()
            await done.wait()

    task = asyncio.create_task(serve())
    await ready.wait()
    yield api
    done.set()
    await task


async def sign_in(engine: AsyncEngine, user_id: UUID) -> str:
    token = secrets.token_urlsafe(16)
    async with engine.begin() as conn:
        await conn.execute(
            t.user_tokens.insert().values(token_hash=hash_token(token), user_id=user_id)
        )
    return token


def http(app: FastAPI, token: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url=LOCAL,
        headers={"Authorization": f"Bearer {token}"},
    )


def scripted(lines: list[str]) -> tuple[Io, StringIO]:
    """A terminal whose user types `lines`, one per prompt; the transcript is in the StringIO."""
    out = StringIO()
    console = Console(file=out, width=120, highlight=False, markup=False, color_system=None)
    queue = list(lines)

    def read(prompt: str) -> str:
        console.print(prompt, end="")
        if not queue:
            raise EOFError
        line = queue.pop(0)
        console.print(line)
        return line

    async def no_wait(seconds: float) -> None:
        return None

    return Io(console=console, read=read, pause=no_wait), out


def najma(app: FastAPI, token: str, io: Io) -> Client:
    return connect(f"{LOCAL}/mcp", token, io, http=http(app, token))


async def web(app: FastAPI, token: str, path: str) -> Any:
    async with http(app, token) as client:
        response = await client.get(path)
    response.raise_for_status()
    return response.json()


async def test_the_server_lists_the_converse_tools_and_needs_a_sign_in(app: FastAPI) -> None:
    io, _ = scripted([])
    async with najma(app, "not-a-real-code", io) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert set(TOOLS) <= names
        assert {"chat", "confirm", "finish_round", "goals"} <= names
        result = await client.call_tool("read_profile", {})
    assert result.is_error and NOT_SIGNED_IN in str(result.content)


async def test_uw19_profile_and_goal_match_the_web_app(app: FastAPI, aengine: AsyncEngine) -> None:
    user_id = await returning_user(aengine)
    token = await sign_in(aengine, user_id)
    io, out = scripted(["y", "n"])
    async with najma(app, token, io) as client:
        await main.show_profile(client, io)
        await main.set_goal(client, io, "working memory", 9, date(2026, 11, 3))
        await main.set_goal(client, io, "inhibition", 9, date(2026, 11, 3))  # answered "n"
        await main.show_goals(client, io)
    text = out.getvalue()

    twin = await web(app, token, "/twin")
    registry = load_registry()
    for view in twin["dims"]:
        if view["n"]:  # the same numbers the dashboard shows
            name = registry.dimension(view["dim"]).name
            row = f"{name} +{pct(view['percent'])}% +\\({pct(view['percent_low'])}-"
            assert re.search(row, text), name

    [goal] = await web(app, token, "/goals")  # only the goal the user said yes to
    assert goal["dim"] == "working_memory" and goal["due"] == "2026-11-03"
    assert "Shall I set this goal?" in text and "[F1] Goal: Working memory range within" in text
    assert f"±{goal['target']}" in text.split("Rounds left")[-1]
    assert "haven't changed anything" in text
    async with aengine.connect() as conn:
        events = (
            await conn.execute(
                select(func.count())
                .select_from(t.events)
                .where(t.events.c.user_id == user_id, t.events.c.type == "goal.set")
            )
        ).scalar_one()
    assert events == 1


async def test_uw19_chat_shows_the_profile_and_sets_a_goal(
    app: FastAPI, aengine: AsyncEngine
) -> None:
    user_id = await returning_user(aengine)
    token = await sign_in(aengine, user_id)
    io, out = scripted(["set a goal for working memory ±9 by 3 Nov", "y", "quit"])
    async with najma(app, token, io) as client:
        await Chat(client, io, WEB).run("chat", {"message": "show my profile"})
    text = out.getvalue()
    assert "Najma (Zitouna):" in text and "80% range" in text  # the coach, then the table
    assert "Shall I set this goal?" in text and "Goal set" in text and "[y/n]" in text
    assert "narrower than ±" in text  # ±9 is tighter than the range can get: Najma says so
    [goal] = await web(app, token, "/goals")
    assert goal["dim"] == "working_memory" and goal["target"] >= 9 and goal["due"].endswith("11-03")


async def test_text_game_played_in_the_terminal_is_scored(
    app: FastAPI, aengine: AsyncEngine
) -> None:
    user_id = await returning_user(aengine)
    token = await sign_in(aengine, user_id)
    words = " ".join(games.fallback_list({"seed": 0, "knobs": {"list_length": 99}}))
    io, out = scripted(["y", "", words, "quit"])
    async with najma(app, token, io) as client:
        await Chat(client, io, WEB).run("start_game", {"game_id": "market_list"})
    text = out.getvalue()
    assert "Play Market List now?" in text
    async with aengine.connect() as conn:
        round_ = (
            await conn.execute(
                select(t.rounds).where(
                    t.rounds.c.user_id == user_id, t.rounds.c.game_id == "market_list"
                )
            )
        ).one()
        trials = (
            await conn.execute(select(t.trials).where(t.trials.c.round_id == round_.round_id))
        ).all()
    assert round_.status == "completed" and round_.scored_at is not None
    assert trials and all(tr.correct for tr in trials)  # every word typed back
    assert len({tr.trial_id for tr in trials}) == len(trials)


async def test_a_browser_game_hands_the_session_to_the_web_app(
    app: FastAPI, aengine: AsyncEngine
) -> None:
    user_id = await returning_user(aengine)
    token = await sign_in(aengine, user_id)
    io, out = scripted(["quit"])
    async with najma(app, token, io) as client:
        chat = Chat(client, io, WEB)
        await chat.run("start_game", {"game_id": "arrow_storm"})
    match = re.search(
        r"open http://localhost:5173/\?session=([0-9a-f-]{36}) to play it", out.getvalue()
    )
    assert match, out.getvalue()
    pending = await web(app, token, f"/sessions/{match.group(1)}/pending")
    assert pending["pending"]["payload"]["spec"]["game_id"] == "arrow_storm"


def test_terminal_games_match_the_registry() -> None:
    assert {g.id for g in load_registry().games if g.terminal} == set(games.GAMES)


async def test_a_write_tool_called_directly_asks_first(app: FastAPI, aengine: AsyncEngine) -> None:
    user_id = await new_user(aengine)
    token = await sign_in(aengine, user_id)
    io, _ = scripted(["y"])
    async with najma(app, token, io) as client:
        answer = await call(client, "update_settings", {"success_mode": "chill"})
    assert "Games now aim for about" in answer["reply"]
    async with aengine.connect() as conn:
        mode = (
            await conn.execute(select(t.users.c.success_mode).where(t.users.c.user_id == user_id))
        ).scalar_one()
    assert mode == "chill"


# The real command against a real server -------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server(db_url: str, tmp_path: Any) -> Any:
    port = free_port()
    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "QDRANT_URL": "http://127.0.0.1:9",  # memory off: not needed here
        "NAJMA_MEMORY_DIR": str(tmp_path),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.api.main:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health").status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail(proc.stderr.read().decode() if proc.stderr else "server didn't start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=20)


async def test_uw19_cli_process(server: str, aengine: AsyncEngine, tmp_path: Any) -> None:
    user_id = await returning_user(aengine)
    token = await sign_in(aengine, user_id)
    env = {
        **os.environ,
        "NAJMA_URL": f"{server}/mcp",
        "NAJMA_TOKEN": token,
        "XDG_CONFIG_HOME": str(tmp_path),
        "COLUMNS": "120",
    }

    async def najma_cmd(*args: str, typed: str = "") -> str:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "cli", *args,
            cwd=ROOT, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        out, err = await asyncio.wait_for(proc.communicate(typed.encode()), timeout=180)
        assert proc.returncode == 0, (out + err).decode()
        return out.decode()

    async with httpx.AsyncClient(
        base_url=server, headers={"Authorization": f"Bearer {token}"}
    ) as web_app:
        shown = await najma_cmd("profile")
        twin = (await web_app.get("/twin")).json()
        measured = [v for v in twin["dims"] if v["n"]]
        assert measured and all(f"{pct(v['percent'])}%" in shown for v in measured)
        said = await najma_cmd(
            "goal", "working memory", "--within", "9", "--by", "2026-11-03", typed="y\n"
        )
        assert "Goal set" in said
        assert "Working memory" in await najma_cmd("goals")
        chatted = await najma_cmd("chat", "show", "my", "profile", typed="quit\n")
        assert "Najma (Zitouna):" in chatted and "See you soon." in chatted
        goals = (await web_app.get("/goals")).json()
    assert [g["due"] for g in goals] == ["2026-11-03"]
