"""MCP tool server (docs/plan/02 and 03, converse subgraph; UW19).

The `najma` CLI, and any other MCP client, talks to the same agent as the web app: `chat` runs
the LangGraph session through the web app's SessionRunner, and the converse tools are the
functions in `backend.agent.tools`. Both read and write the same rows, so the terminal and the
browser always show the same profile and goals.

Calls are signed in with the user's bearer token in the `Authorization` header, the token the web
app uses. Write tools ask first, like the confirm card in the web app: the first call returns an
MCP input request (the 2026-07-28 multi-round flow) with Najma's question and the facts behind
each number in it, and nothing is written until the client answers yes. API keys never pass
through here (AGENTS.md rule 9).
"""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Any
from uuid import UUID, uuid4, uuid5

from mcp.server.elicitation import AcceptedElicitation
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    ToolAnnotations,
)
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from pydantic import AwareDatetime, BaseModel, Field, JsonValue
from sqlalchemy import select

from backend.agent import tools
from backend.agent.context import NajmaContext
from backend.agent.nodes.converse import user_timezone
from backend.agent.runner import SessionNotFound, SessionRunner
from backend.agent.slots import LifeEvent, local_tz
from backend.agent.state import NajmaState
from backend.api.goals import goal_views
from backend.contracts.common import (
    Contract,
    DimensionId,
    GameId,
    Milliseconds,
    Persona,
    SuccessMode,
)
from backend.contracts.exercise import ExerciseSpec, RoundResult, RoundStatus, StopReason
from backend.contracts.facts import FactsPacket
from backend.contracts.session import ToolCall, ToolName, ToolOutcome
from backend.contracts.trial import TrialEvent
from backend.contracts.views import GoalView
from backend.db import tables as t
from backend.db.twin_store import (
    ForeignRound,
    RoundNotFound,
    read_twin,
    record_trials,
    user_for_token,
)

INSTRUCTIONS = (
    "Najma is a practice coach with short brain games. Use `chat` to talk to Najma as the "
    "user would: it picks games, explains its picks and sets goals. Read tools return facts with "
    "ids: answer only from those facts, cite them, and always give a skill as its range, never "
    "a single number. Write tools ask the user first."
)
NOT_SIGNED_IN = "Not signed in. Run `najma login` with the sign-in code from Settings."
NO_SESSION = UUID(int=0)  # reads outside a session: they write nothing, so no session is made
CONFIRM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"confirmed": {"type": "boolean", "title": "Go ahead?"}},
    "required": ["confirmed"],
}


class Confirm(BaseModel):
    confirmed: bool = Field(title="Go ahead?")


NOTHING_CHANGED = "Okay, I haven't changed anything."

Message = Annotated[str, Field(min_length=1, max_length=2000)]


# What the tools return ------------------------------------------------------------------------


class FactOut(Contract):
    id: str
    text: str


class Answer(Contract):
    """What a converse tool found or did."""

    reply: str | None = Field(default=None, description="Najma's answer, when it is fixed text")
    instruction: str | None = Field(
        default=None, description="Without a reply: how to answer from the facts, citing them"
    )
    facts: list[FactOut] = Field(default_factory=list)


class Skill(Contract):
    dim: DimensionId
    name: str
    percent: float
    low: float = Field(description="80% range, low end")
    high: float = Field(description="80% range, high end")
    rounds: int
    still_learning: bool


class Profile(Answer):
    skills: list[Skill] = Field(description="Every skill, as the web app's Brain Twin shows it")


class Waiting(Contract):
    """What the session is paused on."""

    type: str = Field(description="'confirm' (a yes or no) or 'exercise' (a game to play)")
    prompt: str | None = None
    tool: str | None = None
    facts: list[FactOut] = Field(default_factory=list)
    game_id: GameId | None = None
    game_name: str | None = None
    terminal: bool = Field(default=False, description="The game has a text version")
    reason: str | None = None
    spec: dict[str, JsonValue] | None = None


class DecisionOut(Contract):
    decision_id: UUID
    node: str
    reason: str


class Turn(Contract):
    session_id: UUID
    persona: str
    said: list[str] = Field(description="What Najma said, sentence by sentence, with citations")
    decisions: list[DecisionOut]
    tool: str | None = Field(default=None, description="The converse tool this turn used")
    waiting: Waiting | None = None


class TrialAnswer(Contract):
    """One answer from a text game, checked by the client the way the browser plugin does."""

    trial_index: int = Field(ge=0)
    practice: bool = False
    stimulus: dict[str, JsonValue]
    response: dict[str, JsonValue] | None = None
    correct: bool | None
    rt_ms: Milliseconds | None = None
    ts: AwareDatetime


# Helpers --------------------------------------------------------------------------------------


def _facts(packet: FactsPacket) -> list[FactOut]:
    pairs = [(f.id, f.text) for f in packet.facts]
    pairs += [(m.id, m.text) for m in packet.memories]
    pairs += [(k.id, k.text) for k in packet.knowledge]
    return [FactOut(id=i, text=text) for i, text in pairs]


def _answer(outcome: ToolOutcome) -> Answer:
    return Answer(
        reply=outcome.reply or (None if outcome.instruction else outcome.fallback),
        instruction=outcome.instruction,
        facts=_facts(outcome.facts),
    )


def _question(call: ToolCall) -> str:
    """Najma's question with the facts its numbers come from, as the confirm card shows them."""
    lines = [f"[{f.id}] {f.text}" for f in _facts(call.facts)]
    return "\n\n".join([call.prompt or "Shall I go ahead?", *(["\n".join(lines)] if lines else [])])


def _state(raw: str | None) -> tuple[UUID | None, UUID | None]:
    """The call id and session of a write that is waiting for its answer."""
    try:
        call_id, session_id = (raw or "").split(":")
        return UUID(call_id), UUID(session_id)
    except ValueError:
        return None, None


def _graph_state(user_id: UUID, session_id: UUID, persona: str) -> NajmaState:
    """The little state a converse tool reads (goal skills, life context) outside the graph."""
    return NajmaState.model_validate(
        {
            "user_id": str(user_id),
            "session_id": str(session_id),
            "trigger": "cli",
            "persona": persona,
        }
    )


def build_server(get_runner: Callable[[], SessionRunner]) -> MCPServer:
    """The server; `get_runner` returns the app's SessionRunner once the lifespan has made it."""
    server: MCPServer = MCPServer("najma", instructions=INSTRUCTIONS, version="0.1.0")

    async def user_of(ctx: Context) -> UUID:
        header = (ctx.headers or {}).get("authorization") or ""
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise ToolError(NOT_SIGNED_IN)
        async with get_runner().services.engine.begin() as conn:
            user_id = await user_for_token(conn, token.strip())
        if user_id is None:
            raise ToolError(NOT_SIGNED_IN)
        return user_id

    async def persona_of(user_id: UUID) -> str:
        async with get_runner().services.engine.connect() as conn:
            persona: str = (
                await conn.execute(select(t.users.c.persona).where(t.users.c.user_id == user_id))
            ).scalar_one()
        return persona

    async def session(user_id: UUID, session_id: UUID | None) -> tuple[UUID, str]:
        runner = get_runner()
        if session_id is None:
            session_id = await runner.create_session(user_id, "cli")
        try:
            return session_id, await runner.persona(user_id, session_id)
        except SessionNotFound as exc:
            raise ToolError("Unknown session") from exc

    def waiting(payload: dict[str, Any]) -> Waiting:
        if payload.get("type") == "confirm":
            return Waiting(
                type="confirm",
                prompt=payload.get("prompt"),
                tool=payload.get("tool"),
                facts=_facts(FactsPacket.model_validate(payload.get("facts") or {})),
            )
        if payload.get("type") == "exercise":
            spec = ExerciseSpec.model_validate(payload["spec"])
            game = get_runner().services.registry.game(spec.game_id)
            return Waiting(
                type="exercise",
                game_id=spec.game_id,
                game_name=game.name,
                terminal=game.terminal,
                reason=spec.reason,
                spec=payload["spec"],
            )
        return Waiting(type=str(payload.get("type", "other")))

    async def turn(user_id: UUID, session_id: UUID, persona: str, **kw: Any) -> Turn:
        runner = get_runner()
        events = [e async for e in runner.run(user_id, session_id, **kw)]
        snapshot = await runner.graph.aget_state(runner.config(session_id))
        outcome = snapshot.values.get("tool_outcome")
        paused = next((e["payload"] for e in events if e["kind"] == "interrupt"), None)
        return Turn(
            session_id=session_id,
            persona=persona,
            said=[e["text"] for e in events if e["kind"] == "say"],
            decisions=[
                DecisionOut(decision_id=e["decision_id"], node=e["node"], reason=e["reason"])
                for e in events
                if e["kind"] == "decision"
            ],
            tool=outcome.name if isinstance(outcome, ToolOutcome) else None,
            waiting=waiting(paused) if paused is not None else None,
        )

    async def pending(user_id: UUID, session_id: UUID) -> dict[str, Any]:
        try:
            paused = await get_runner().pending(user_id, session_id)
        except SessionNotFound as exc:
            raise ToolError("Unknown session") from exc
        if paused is None:
            raise ToolError("This session isn't waiting for anything")
        payload: dict[str, Any] = paused["payload"]
        return payload

    async def read(
        ctx: Context, name: ToolName, args: Contract, session_id: UUID | None
    ) -> tuple[ToolOutcome, NajmaContext]:
        user_id = await user_of(ctx)
        if session_id is not None:
            _, persona = await session(user_id, session_id)
        else:
            persona = await persona_of(user_id)
        sid = session_id or NO_SESSION
        najma = await get_runner().context_for(user_id, sid)
        state = _graph_state(user_id, sid, persona)
        call = ToolCall(call_id=uuid4(), name=name, args=args.model_dump(mode="json"))
        outcome, _ = await tools.TOOLS[name].run(najma, state, call)
        return outcome, najma

    async def write(
        ctx: Context,
        name: ToolName,
        session_id: UUID | None,
        propose: Callable[[NajmaContext, UUID], Awaitable[ToolCall | ToolOutcome]],
    ) -> Answer | InputRequiredResult:
        """Propose, ask, then write: the same steps as the converse subgraph's confirm."""
        user_id = await user_of(ctx)
        call_id, asked_in = _state(ctx.request_state)
        sid, persona = await session(user_id, asked_in or session_id)
        najma = await get_runner().context_for(user_id, sid)
        proposal = await propose(najma, call_id or uuid4())
        if isinstance(proposal, ToolOutcome):  # nothing to ask, e.g. an experiment is running
            return _answer(proposal)
        if ctx.protocol_version in HANDSHAKE_PROTOCOL_VERSIONS:  # older clients: ask in place
            asked = await ctx.elicit(_question(proposal), Confirm)
            yes = isinstance(asked, AcceptedElicitation) and asked.data.confirmed
        else:
            reply = (ctx.input_responses or {}).get("confirm")
            if not isinstance(reply, ElicitResult):
                ask = ElicitRequestFormParams(
                    message=_question(proposal), requested_schema=CONFIRM_SCHEMA
                )
                return InputRequiredResult(
                    input_requests={"confirm": ElicitRequest(params=ask)},
                    request_state=f"{proposal.call_id}:{sid}",
                )
            yes = reply.action == "accept" and (reply.content or {}).get("confirmed") is True
        if not yes:
            return Answer(reply=NOTHING_CHANGED)
        state = _graph_state(user_id, sid, persona)
        outcome, _ = await tools.TOOLS[name].run(najma, state, proposal)
        return _answer(outcome)

    # Session tools ----------------------------------------------------------------------------

    @server.tool()
    async def chat(
        ctx: Context, message: Message | None = None, session_id: UUID | None = None
    ) -> Turn:
        """Say something to Najma, as the user. Without a session_id this starts a session (and
        without a message, Najma suggests a game). The turn may end waiting for a yes or no
        (`confirm`) or for a game (`finish_round`)."""
        user_id = await user_of(ctx)
        sid, persona = await session(user_id, session_id)
        return await turn(user_id, sid, persona, message=message)

    @server.tool()
    async def confirm(ctx: Context, session_id: UUID, yes: bool) -> Turn:
        """Answer the question a session is waiting on (for example "Shall I set this goal?")."""
        user_id = await user_of(ctx)
        _, persona = await session(user_id, session_id)
        if (await pending(user_id, session_id)).get("type") != "confirm":
            raise ToolError("This session is waiting for a game, not a yes or no")
        return await turn(user_id, session_id, persona, resume={"confirmed": yes})

    @server.tool()
    async def finish_round(
        ctx: Context,
        session_id: UUID,
        round_id: UUID,
        answers: list[TrialAnswer],
        started_at: AwareDatetime,
        ended_at: AwareDatetime,
        status: RoundStatus = "completed",
        stop_reason: StopReason | None = None,
        metrics: dict[str, float] | None = None,
    ) -> Turn:
        """Send the answers of the game the session is waiting on; Najma scores it and goes on.
        Sending the same answers twice records them once."""
        user_id = await user_of(ctx)
        _, persona = await session(user_id, session_id)
        payload = await pending(user_id, session_id)
        if payload.get("type") != "exercise":
            raise ToolError("This session is waiting for a yes or no, not a game")
        spec = ExerciseSpec.model_validate(payload["spec"])
        if spec.round_id != round_id:
            raise ToolError("That round isn't the one waiting")
        trials = [
            TrialEvent(
                trial_id=uuid5(round_id, f"trial:{a.trial_index}"),
                round_id=round_id,
                session_id=session_id,
                game_id=spec.game_id,
                level=spec.level,
                trial_index=a.trial_index,
                practice=a.practice,
                stimulus=a.stimulus,
                response=a.response,
                correct=a.correct,
                rt_ms=a.rt_ms,
                ts=a.ts,
            )
            for a in answers
        ]
        if trials:
            try:
                async with get_runner().services.engine.begin() as conn:
                    await record_trials(conn, user_id, trials)
            except (RoundNotFound, ForeignRound) as exc:
                raise ToolError("That round isn't the one waiting") from exc
        result = RoundResult(
            round_id=round_id,
            game_id=spec.game_id,
            status=status,
            stop_reason=stop_reason,
            trial_count=sum(not a.practice for a in answers),
            metrics=metrics or {},
            final_level=spec.level,
            started_at=started_at,
            ended_at=ended_at,
        )
        return await turn(user_id, session_id, persona, resume=result.model_dump(mode="json"))

    @server.tool()
    async def start_game(
        ctx: Context,
        game_id: GameId | None = None,
        dim: DimensionId | None = None,
        session_id: UUID | None = None,
    ) -> Turn:
        """Ask for a round, of a given game or skill if wanted. Najma's policy still picks the
        level, and may say why it suggests something else."""
        registry = get_runner().services.registry
        if game_id is not None and not registry.game(game_id).available:
            raise ToolError(f"{registry.game(game_id).name} isn't ready to play yet")
        if game_id is not None:
            ask = f"Let's play {registry.game(game_id).name}"
        elif dim is not None:
            ask = f"Let's play a {registry.dimension(dim).name.lower()} game"
        else:
            ask = "Let's play"
        return await chat(ctx, ask, session_id)

    # Read tools -------------------------------------------------------------------------------

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def read_profile(
        ctx: Context,
        dim: DimensionId | None = None,
        question: str = "",
        session_id: UUID | None = None,
    ) -> Profile:
        """The user's skill estimates, each with its 80% range, as the Brain Twin shows them."""
        args = tools.ReadProfileArgs(dim=dim, question=question)
        outcome, najma = await read(ctx, "read_profile", args, session_id)
        registry = najma.services.registry
        async with najma.services.engine.connect() as conn:
            twin = await read_twin(conn, najma.user_id, norms=najma.services.norms)
        skills = [
            Skill(
                dim=v.dim,
                name=registry.dimension(v.dim).name,
                percent=v.percent,
                low=v.percent_low,
                high=v.percent_high,
                rounds=v.n,
                still_learning=v.still_learning,
            )
            for v in twin.dims
            if dim is None or v.dim == dim
        ]
        answer = _answer(outcome)
        return Profile(**answer.model_dump(), skills=skills)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def get_history(
        ctx: Context,
        dim: DimensionId | None = None,
        days: Annotated[int, Field(ge=1, le=3650)] = 30,
        question: str = "",
        session_id: UUID | None = None,
    ) -> Answer:
        """How a skill (or every skill) changed over the last `days` days, with ranges."""
        args = tools.GetHistoryArgs(dim=dim, days=days, question=question)
        return _answer((await read(ctx, "get_history", args, session_id))[0])

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def search_memory(
        ctx: Context,
        query: Annotated[str, Field(min_length=1, max_length=300)],
        session_id: UUID | None = None,
    ) -> Answer:
        """What Najma remembers about the user that matches the query."""
        args = tools.SearchMemoryArgs(query=query)
        return _answer((await read(ctx, "search_memory", args, session_id))[0])

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def explain(
        ctx: Context,
        decision_id: UUID | None = None,
        question: str = "",
        session_id: UUID | None = None,
    ) -> Answer:
        """Why Najma chose something: the latest game pick, or a given decision."""
        args = tools.ExplainArgs(decision_id=decision_id, question=question)
        return _answer((await read(ctx, "explain", args, session_id))[0])

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def goals(ctx: Context) -> list[GoalView]:
        """The user's active goals and how far along each is, as the Goals page shows them."""
        user_id = await user_of(ctx)
        async with get_runner().services.engine.connect() as conn:
            return await goal_views(conn, user_id, get_runner().services.registry)

    # Write tools: each asks the user first -----------------------------------------------------

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=True))
    async def set_goal(
        ctx: Context,
        dim: DimensionId,
        due: date,
        target: Annotated[int | None, Field(ge=1, le=50)] = None,
        session_id: UUID | None = None,
    ) -> Answer | InputRequiredResult:
        """Set a range goal: the skill's range within ± `target` points by `due`. Without a
        target, Najma suggests a reachable one."""

        async def propose(najma: NajmaContext, call_id: UUID) -> ToolCall:
            return await tools.propose_goal(najma, dim, due, call_id, target)

        return await write(ctx, "set_goal", session_id, propose)

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=True))
    async def log_life_context(
        ctx: Context,
        label: Annotated[str, Field(min_length=1, max_length=80)],
        start: AwareDatetime,
        end: AwareDatetime,
        light: bool = False,
        session_id: UUID | None = None,
    ) -> Answer | InputRequiredResult:
        """Note something like a bad night or exams: rounds in that time count less."""
        if end <= start:
            raise ToolError("The end must be after the start")

        async def propose(najma: NajmaContext, call_id: UUID) -> ToolCall:
            tz = local_tz(await user_timezone(najma))
            return tools.propose_life_context(LifeEvent(label, start, end, light), tz, call_id)

        return await write(ctx, "log_life_context", session_id, propose)

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=True))
    async def update_settings(
        ctx: Context,
        persona: Persona | None = None,
        success_mode: SuccessMode | None = None,
        pause_dim: DimensionId | None = None,
        pause_days: Annotated[int, Field(ge=1, le=30)] = 7,
        session_id: UUID | None = None,
    ) -> Answer | InputRequiredResult:
        """Change the coach, the difficulty mode, or stop suggesting a skill for a few days."""
        if persona is None and success_mode is None and pause_dim is None:
            raise ToolError("Say what to change: persona, success_mode or pause_dim")
        args = tools.UpdateSettingsArgs(
            persona=persona, success_mode=success_mode, pause_dim=pause_dim, pause_days=pause_days
        )

        async def propose(najma: NajmaContext, call_id: UUID) -> ToolCall:
            return tools.propose_settings(najma, args, call_id)

        return await write(ctx, "update_settings", session_id, propose)

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=True))
    async def start_experiment(
        ctx: Context, session_id: UUID | None = None
    ) -> Answer | InputRequiredResult:
        """Test whether the user does better in the morning or the evening (6 sessions)."""

        async def propose(najma: NajmaContext, call_id: UUID) -> ToolCall | ToolOutcome:
            running = await tools.experiment_in_progress(najma)
            return running or await tools.propose_experiment(najma, call_id)

        return await write(ctx, "start_experiment", session_id, propose)

    return server
