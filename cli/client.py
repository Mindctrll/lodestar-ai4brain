"""The connection to Najma's MCP tool server, the sign-in code, and the terminal's input and
output (one `Io`, so tests can script the user)."""

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
from mcp import Client
from mcp.client.session import ClientRequestContext
from mcp.client.streamable_http import streamable_http_client
from mcp_types import ElicitRequestParams, ElicitResult, Implementation, TextContent
from rich.console import Console

from cli import render

DEFAULT_URL = "http://localhost:8000/mcp"
DEFAULT_WEB = "http://localhost:5173"
TIMEOUT_S = 180.0  # a turn can include a local model's draft


class NajmaError(Exception):
    """A tool said no (not signed in, unknown session, ...); the message is for the user."""


@dataclass
class Io:
    console: Console
    read: Callable[[str], str]  # one line from the user; EOFError when they're done
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep
    clock: Callable[[], float] = time.monotonic


def terminal_io() -> Io:
    console = Console(highlight=False, markup=False)  # styles come from Text, never markup
    return Io(console=console, read=lambda prompt: console.input(prompt))


def ask_yes(io: Io, prompt: str = "[y/n] ") -> bool:
    while True:
        try:
            answer = io.read(prompt).strip().lower()
        except EOFError:
            return False
        if answer in ("y", "yes", "ok", "sure"):
            return True
        if answer in ("n", "no", "not now", ""):
            return False
        io.console.print("Please answer y or n.")


# The sign-in code -----------------------------------------------------------------------------


def token_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "najma" / "token"


def saved_token() -> str | None:
    try:
        return token_path().read_text().strip() or None
    except OSError:
        return None


def save_token(token: str) -> None:
    """Only the owner can read it, like an SSH key."""
    path = token_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(token.strip() + "\n")


def forget_token() -> None:
    token_path().unlink(missing_ok=True)


# The MCP client -------------------------------------------------------------------------------


def connect(url: str, token: str, io: Io, http: httpx2.AsyncClient | None = None) -> Client:
    """A client signed in as the user. Write tools ask before writing; the question comes back
    here as an MCP input request and the user answers it in the terminal."""

    async def answer(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        render.question(io.console, getattr(params, "message", ""))
        if ask_yes(io):
            return ElicitResult(action="accept", content={"confirmed": True})
        return ElicitResult(action="decline")

    client = http or httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}, timeout=httpx2.Timeout(TIMEOUT_S)
    )
    return Client(
        streamable_http_client(url, http_client=client),
        elicitation_callback=answer,
        client_info=Implementation(name="najma-cli", version="0.1.0"),
        read_timeout_seconds=TIMEOUT_S,
    )


async def call(najma: Client, tool: str, args: dict[str, Any] | None = None) -> Any:
    """Call a tool and return its structured result; a tool error becomes a NajmaError."""
    result = await najma.call_tool(tool, {k: v for k, v in (args or {}).items() if v is not None})
    if result.is_error:
        text = " ".join(c.text for c in result.content if isinstance(c, TextContent))
        raise NajmaError(text or f"{tool} failed")
    data = result.structured_content or {}
    return data["result"] if set(data) == {"result"} else data
