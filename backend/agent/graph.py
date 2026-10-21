"""The Najma agent loop as a LangGraph graph (docs/plan/03, "The loop in one picture").

Two changes from the plan's picture: every scored round gets an after-game coach message, so the
path is score_update -> monitor -> reflect -> coach -> remember, and `remember` uses the monitor's
verdict to continue (plan_next), finish (consolidate) or end the run. Goal, life-context and
settings turns go through the converse subgraph's tools (confirm before writing) instead of a
separate update_user node.
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Send
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.agent.context import NajmaContext
from backend.agent.nodes import converse, gate, perceive, play, talk, twin
from backend.agent.state import NajmaState


def fan_out(state: NajmaState) -> list[Send]:
    return [Send(name, state) for name in perceive.PERCEIVE_NODES]


def build_graph() -> StateGraph[NajmaState, NajmaContext, Any, Any]:
    g: StateGraph[NajmaState, NajmaContext, Any, Any] = StateGraph(
        NajmaState, context_schema=NajmaContext
    )
    g.add_node("ingest", gate.ingest)
    for name in perceive.PERCEIVE_NODES:
        g.add_node(name, getattr(perceive, name))
    g.add_node("safety_gate", gate.safety_gate)
    g.add_node("refuse", gate.refuse)
    g.add_node("route_intent", gate.route_intent)
    g.add_node("plan_next", play.plan_next)
    g.add_node("prepare_exercise", play.prepare_exercise)
    g.add_node("play", play.play)
    g.add_node("score_update", play.score_update)
    g.add_node("monitor", play.monitor)
    g.add_node("reflect", talk.reflect)
    g.add_node("coach", talk.coach)
    for name in ("converse", "confirm", "use_tool", "answer"):
        g.add_node(name, getattr(converse, name))
    g.add_node("twin_chat", twin.twin_chat)
    g.add_node("respond", talk.respond)
    g.add_node("remember", talk.remember)
    g.add_node("consolidate", talk.consolidate)

    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", fan_out, list(perceive.PERCEIVE_NODES))
    g.add_edge(list(perceive.PERCEIVE_NODES), "safety_gate")
    g.add_conditional_edges("safety_gate", gate.after_safety, ["refuse", "route_intent"])
    g.add_conditional_edges("refuse", gate.after_refuse, {"play": "play", "__end__": END})
    g.add_conditional_edges(
        "route_intent", gate.after_route, ["plan_next", "converse", "twin_chat"]
    )
    g.add_conditional_edges("converse", converse.after_converse, ["confirm", "use_tool", "answer"])
    g.add_edge("confirm", "use_tool")
    g.add_edge("use_tool", "answer")
    g.add_edge("plan_next", "prepare_exercise")
    g.add_edge("prepare_exercise", "play")
    g.add_edge("play", "score_update")
    g.add_edge("score_update", "monitor")
    g.add_edge("monitor", "reflect")
    g.add_edge("reflect", "coach")
    g.add_edge("coach", "remember")
    for name in ("answer", "twin_chat"):
        g.add_edge(name, "respond")
    g.add_edge("respond", "remember")
    g.add_conditional_edges(
        "remember",
        talk.after_remember,
        {"plan_next": "plan_next", "play": "play", "consolidate": "consolidate", "__end__": END},
    )
    g.add_edge("consolidate", END)
    return g


def _contract_types() -> list[tuple[str, str]]:
    """Every contract model, allowlisted for checkpoint deserialisation."""
    import inspect

    from pydantic import BaseModel

    from backend.contracts import (
        acs,
        affect,
        common,
        decision,
        events,
        exercise,
        facts,
        llm,
        memory,
        session,
        trial,
        twin,
    )  # fmt: skip

    found = []
    for module in (acs, affect, common, decision, events, exercise, facts, llm, memory, session,
                   trial, twin):  # fmt: skip
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseModel)
                and obj.__module__ == module.__name__
            ):
                found.append((module.__name__, name))
    return found


def checkpoint_pool(url: str) -> AsyncConnectionPool[Any]:
    """The checkpointer's connection pool, not yet open. Each connection is checked before it is
    handed out, so sessions carry on after Postgres restarts or drops connections (WP4.1)."""
    return AsyncConnectionPool(
        url,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
        check=AsyncConnectionPool.check_connection,
    )


def checkpointer(pool: Any) -> BaseCheckpointSaver[Any]:
    """The Postgres checkpointer, with our state types allowlisted."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    # The default allows every type with a warning (to be blocked in a later version), so the
    # allowlist is given explicitly.
    serde = JsonPlusSerializer(allowed_msgpack_modules=_contract_types())
    return AsyncPostgresSaver(pool, serde=serde)


def compile_graph(
    checkpointer: BaseCheckpointSaver[Any] | None, store: BaseStore | None = None
) -> CompiledStateGraph[NajmaState, NajmaContext, Any, Any]:
    return build_graph().compile(checkpointer=checkpointer, store=store, name="najma")
