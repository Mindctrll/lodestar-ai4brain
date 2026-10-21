import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.agent.state import NajmaState
from backend.contracts.affect import AffectReading
from backend.contracts.events import EVENT_TYPES, parse_event
from backend.contracts.export import build_openapi
from backend.contracts.facts import Fact, FactsPacket
from backend.contracts.twin import ForecastBand

NOW = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)

# docs/plan/04, "Event types" (experiment.* expanded).
PLAN_EVENT_TYPES = {
    "session.started", "trial.recorded", "round.completed", "twin.updated", "acs.observed",
    "affect.estimated", "affect.labelled", "context.added", "goal.set", "experiment.started",
    "experiment.session_logged", "experiment.completed", "consent.changed", "memory.written",
    "session.ended", "data.exported", "twin.snapshot", "llm.selection_changed",
}  # fmt: skip


def test_event_types_match_plan() -> None:
    assert set(EVENT_TYPES) == PLAN_EVENT_TYPES


def test_trial_event_round_trips() -> None:
    raw = {
        "user_id": str(uuid4()),
        "session_id": str(uuid4()),
        "ts": NOW.isoformat(),
        "type": "trial.recorded",
        "payload": {
            "trial_id": str(uuid4()),
            "round_id": str(uuid4()),
            "session_id": str(uuid4()),
            "game_id": "echo",
            "level": 0.4,
            "trial_index": 0,
            "stimulus": {"letter": "K"},
            "response": {"key": "j"},
            "correct": True,
            "rt_ms": 512.0,
            "ts": NOW.isoformat(),
        },
    }
    event = parse_event(raw)
    assert event.type == "trial.recorded"
    assert parse_event(event.model_dump(mode="json")) == event


def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_event({"user_id": str(uuid4()), "ts": NOW.isoformat(), "type": "x", "payload": {}})


def test_forecast_is_a_range() -> None:
    ForecastBand(dim="reasoning", sessions_ahead=5, low=0.1, median=0.2, high=0.4, source="model")
    with pytest.raises(ValidationError, match="low <= median <= high"):
        ForecastBand(
            dim="reasoning", sessions_ahead=5, low=0.3, median=0.2, high=0.4, source="model"
        )


def test_affect_fusion_keeps_behaviour_dominant() -> None:
    AffectReading(frustration_p=0.4, fatigue_p=0.1, sources=["behaviour"], behaviour_weight=0.7)
    with pytest.raises(ValidationError):
        AffectReading(frustration_p=0.4, fatigue_p=0.1, sources=["camera"], behaviour_weight=0.5)


def test_facts_packet_ids_are_unique() -> None:
    fact = Fact(id="F1", text="Working memory estimate 0.66")
    assert FactsPacket(facts=[fact]).text_of("F1") == fact.text
    with pytest.raises(ValidationError, match="unique"):
        FactsPacket(facts=[fact, fact])


def test_state_builds_with_defaults() -> None:
    state = NajmaState(user_id="u", session_id="s", trigger="ui", persona="hikma")
    assert state.budget.max_rounds == 3
    assert state.decisions == []


def test_life_context_must_end_after_start() -> None:
    from backend.contracts.twin import LifeContextWindow

    with pytest.raises(ValidationError):
        LifeContextWindow(
            context_id=uuid4(),
            label="exam week",
            start=NOW,
            end=NOW - timedelta(days=1),
            weight=0.5,
        )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_profile_code_never_imports_affect() -> None:
    """AGENTS.md rule 3: no code path from biometric or affect signals to the Brain Twin."""
    for root in (Path("backend/scoring"), Path("backend/db")):
        for path in root.rglob("*.py"):
            assert "backend.contracts.affect" not in _imports(path), path


def test_openapi_file_is_up_to_date() -> None:
    on_disk = json.loads(Path("contracts/openapi.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(build_openapi())), "run `make contracts`"
