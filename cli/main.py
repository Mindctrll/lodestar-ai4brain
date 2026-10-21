"""The `najma` command (UW19): chat, play text games, see your profile and goals, set a goal.

    najma login            paste the sign-in code from Settings > Terminal
    najma chat             talk to Najma, who suggests a game
    najma play [game]      play a round (text games here, others in the browser)
    najma profile [skill]  your skills with their 80% ranges
    najma goals            your goals and how far along they are
    najma goal SKILL --within 5 --by 2026-11-03
    najma why              why Najma picked the last game

Every command goes through the MCP tool server, so it uses the same agent and data as the web app.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any

import httpx2
import typer
from mcp import Client

from cli import render
from cli.client import (
    DEFAULT_URL,
    DEFAULT_WEB,
    Io,
    NajmaError,
    call,
    connect,
    forget_token,
    save_token,
    saved_token,
    terminal_io,
)
from cli.session import Chat

GOAL_DAYS_DEFAULT = 14  # as in backend/agent/slots.py

app = typer.Typer(
    name="najma",
    help="Najma in your terminal: chat, play text games, see your profile and goals.",
    no_args_is_help=True,
    add_completion=False,
)


@dataclass
class Options:
    url: str
    web: str
    token: str | None


@app.callback()
def main(
    ctx: typer.Context,
    url: Annotated[
        str, typer.Option(envvar="NAJMA_URL", help="Najma's MCP tool server")
    ] = DEFAULT_URL,
    web: Annotated[
        str, typer.Option(envvar="NAJMA_WEB_URL", help="The web app, for browser games")
    ] = DEFAULT_WEB,
    token: Annotated[
        str | None,
        typer.Option(envvar="NAJMA_TOKEN", help="Sign-in code (default: the saved one)"),
    ] = None,
) -> None:
    ctx.obj = Options(url=url, web=web, token=token)


Work = Callable[[Client, Io], Awaitable[None]]


def _unreachable(exc: BaseException) -> bool:
    if isinstance(exc, BaseExceptionGroup):
        return any(_unreachable(e) for e in exc.exceptions)
    return isinstance(exc, (httpx2.TransportError, ConnectionError))


def _run(ctx: typer.Context, work: Work, token: str | None = None) -> None:
    opts: Options = ctx.obj
    io = terminal_io()
    token = token or opts.token or saved_token()
    if not token:
        io.console.print("Not signed in. Run `najma login` with the code from Settings > Terminal.")
        raise typer.Exit(1)

    async def go() -> None:
        async with connect(opts.url, token, io) as najma:
            await work(najma, io)

    try:
        asyncio.run(go())
    except NajmaError as exc:
        io.console.print(str(exc))
        raise typer.Exit(1) from exc
    except KeyboardInterrupt:
        io.console.print("\nSee you soon.")
    except Exception as exc:
        if not _unreachable(exc):
            raise
        io.console.print(f"Can't reach Najma at {opts.url}. Is it running? (`make up`)")
        raise typer.Exit(1) from exc


# What each command does (async, so tests can run them against an in-process server) -----------


async def show_profile(najma: Client, io: Io, skill: str | None = None) -> None:
    dim = await resolve_skill(najma, skill) if skill else None
    profile = await call(najma, "read_profile", {"dim": dim})
    if not any(s["rounds"] for s in profile["skills"]):
        io.console.print("No skills measured yet. Play a round: `najma play`.")
        return
    io.console.print(render.profile_table(profile["skills"]))


async def show_goals(najma: Client, io: Io) -> None:
    goals = await call(najma, "goals")
    if not goals:
        io.console.print("No goals yet. Set one: `najma goal memory --within 5`.")
        return
    io.console.print(render.goals_table(goals))


async def set_goal(najma: Client, io: Io, skill: str, within: int | None, by: date | None) -> None:
    dim = await resolve_skill(najma, skill)
    due = by or date.today() + timedelta(days=GOAL_DAYS_DEFAULT)
    answer = await call(
        najma, "set_goal", {"dim": dim, "due": due.isoformat(), "target": within}
    )  # the server asks first; the question is answered in the terminal (cli.client.connect)
    show_answer(io, answer)


async def explain(najma: Client, io: Io) -> None:
    show_answer(io, await call(najma, "explain"))


def show_answer(io: Io, answer: dict[str, Any]) -> None:
    if answer.get("reply"):
        io.console.print(render.cited(answer["reply"]))
    else:
        render.facts(io.console, answer.get("facts", []))


async def resolve_skill(najma: Client, text: str) -> str:
    """A skill id or name, or a unique part of one ("memory" is ambiguous; "working" isn't)."""
    skills = (await call(najma, "read_profile"))["skills"]
    wanted = text.strip().lower().replace("_", " ")
    exact = [s for s in skills if wanted in (s["dim"].replace("_", " "), s["name"].lower())]
    if exact:
        return str(exact[0]["dim"])
    partial = [s for s in skills if wanted in s["name"].lower() or wanted in s["dim"]]
    if len(partial) == 1:
        return str(partial[0]["dim"])
    options = ", ".join(s["name"].lower() for s in (partial or skills))
    raise NajmaError(f'Which skill do you mean by "{text}"? Try one of: {options}')


# Commands -------------------------------------------------------------------------------------


@app.command()
def login(
    ctx: typer.Context,
    code: Annotated[str | None, typer.Option(help="The sign-in code from Settings")] = None,
) -> None:
    """Sign in with the code from the web app's Settings > Terminal."""
    io = terminal_io()
    code = (code or io.console.input("Sign-in code: ", password=True)).strip()

    async def check(najma: Client, io: Io) -> None:
        await call(najma, "goals")
        save_token(code)
        io.console.print("Signed in. Try `najma chat`.")

    _run(ctx, check, token=code)


@app.command()
def logout() -> None:
    """Forget the saved sign-in code on this computer."""
    forget_token()
    terminal_io().console.print("Signed out on this computer.")


@app.command()
def chat(
    ctx: typer.Context,
    message: Annotated[list[str] | None, typer.Argument(help="What to say first")] = None,
) -> None:
    """Talk to Najma. Without a message, Najma suggests a game. Type quit to leave."""
    first = " ".join(message or []) or None

    async def work(najma: Client, io: Io) -> None:
        await Chat(najma, io, ctx.obj.web).run("chat", {"message": first})

    _run(ctx, work)


@app.command()
def play(
    ctx: typer.Context,
    game: Annotated[str | None, typer.Argument(help="A game id, e.g. market_list")] = None,
) -> None:
    """Play a round. Text games are played here; others open in the browser."""

    async def work(najma: Client, io: Io) -> None:
        await Chat(najma, io, ctx.obj.web).run("start_game", {"game_id": game})

    _run(ctx, work)


@app.command()
def profile(
    ctx: typer.Context,
    skill: Annotated[str | None, typer.Argument(help="One skill, e.g. 'working memory'")] = None,
) -> None:
    """Your skills, each with its 80% range."""
    _run(ctx, lambda najma, io: show_profile(najma, io, skill))


@app.command()
def goals(ctx: typer.Context) -> None:
    """Your goals and how far along each is."""
    _run(ctx, show_goals)


@app.command()
def goal(
    ctx: typer.Context,
    skill: Annotated[str, typer.Argument(help="The skill, e.g. 'working memory'")],
    within: Annotated[
        int | None, typer.Option(min=1, max=50, help="Range within ± this many points")
    ] = None,
    by: Annotated[
        datetime | None, typer.Option(formats=["%Y-%m-%d"], help="Due date (default: 2 weeks)")
    ] = None,
) -> None:
    """Set a goal: a skill's range within ± N points by a date. Najma asks before saving it."""
    due = by.date() if by else None
    _run(ctx, lambda najma, io: set_goal(najma, io, skill, within, due))


@app.command()
def why(ctx: typer.Context) -> None:
    """Why Najma picked the last game."""
    _run(ctx, explain)
