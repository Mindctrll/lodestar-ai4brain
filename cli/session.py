"""The chat loop: say something, read Lodestar's turn, and follow it up (a yes or no, or a game).

A game with a text version is played right here; any other game opens in the browser, which
picks up this same session (`?session=<id>`).
"""

from typing import Any

from mcp import Client
from rich.text import Text

from cli import games, render
from cli.client import Io, ask_yes, call

QUIT = {"quit", "exit", "bye", "q", ":q"}


class Chat:
    def __init__(self, lodestar: Client, io: Io, web: str) -> None:
        self.lodestar = lodestar
        self.io = io
        self.web = web.rstrip("/")
        self.asked: set[str] = set()  # rounds already offered, so a "no" isn't asked again

    async def run(self, tool: str = "chat", args: dict[str, Any] | None = None) -> None:
        turn = await self.follow(await call(self.lodestar, tool, args))
        while True:
            try:
                line = self.io.read("> ").strip()
            except EOFError:
                line = "quit"
            if line.lower() in QUIT:
                self.io.console.print("See you soon.")
                return
            if line:
                message = {"message": line, "session_id": turn["session_id"]}
                turn = await self.follow(await call(self.lodestar, "chat", message))

    async def follow(self, turn: dict[str, Any]) -> dict[str, Any]:
        """Show a turn, then answer what it waits on, until it waits on the user's next line."""
        while True:
            render.say(self.io.console, turn["persona"], turn["said"])
            if turn.get("tool") == "read_profile":
                await self.profile(turn["session_id"])
            waiting = turn.get("waiting")
            if waiting is None:
                return turn
            if waiting["type"] == "confirm":
                render.question(self.io.console, waiting["prompt"] or "Shall I go ahead?")
                render.facts(self.io.console, waiting["facts"])
                yes = ask_yes(self.io)
                answer = {"session_id": turn["session_id"], "yes": yes}
                turn = await call(self.lodestar, "confirm", answer)
                continue
            if waiting["type"] != "exercise":
                return turn
            played = await self.offer(turn["session_id"], waiting)
            if played is None:
                return turn
            result = {"session_id": turn["session_id"], **played}
            turn = await call(self.lodestar, "finish_round", result)

    async def offer(self, session_id: str, waiting: dict[str, Any]) -> dict[str, Any] | None:
        """Offer the game Lodestar picked; play it here if it has a text version."""
        spec = waiting["spec"]
        if spec["round_id"] in self.asked:
            return None
        self.asked.add(spec["round_id"])
        name = waiting["game_name"]
        if waiting["reason"]:
            self.io.console.print(Text(f"Why this game: {waiting['reason']}", style="dim"))
        if not waiting["terminal"]:
            self.browser(session_id, name)
            return None
        self.io.console.print(f"Play {name} now?", end=" ")
        if not ask_yes(self.io):
            self.io.console.print("Okay. Say 'something else' for another game, or ask me.")
            return None
        try:
            return await games.play(self.io, spec)
        except games.NoContent:
            self.browser(session_id, name)
            return None

    def browser(self, session_id: str, name: str) -> None:
        self.io.console.print(
            f"{name} plays in the browser: open {self.web}/?session={session_id} to play it "
            "there. Or say 'something else'."
        )

    async def profile(self, session_id: str | None = None) -> None:
        profile = await call(self.lodestar, "read_profile", {"session_id": session_id})
        self.io.console.print(render.profile_table(profile["skills"]))
