"""`make contracts`: write the OpenAPI document (with every contract model) and the registry
JSON Schemas. The frontend generates its TypeScript types from the OpenAPI document."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter
from pydantic.json_schema import models_json_schema

from backend.agent.state import LodestarState
from backend.api.main import app
from backend.contracts.acs import AcsEvent
from backend.contracts.affect import AffectReading, BehaviourSignals, BiometricCues
from backend.contracts.decision import Decision
from backend.contracts.events import Event
from backend.contracts.exercise import ExerciseSpec, RoundResult
from backend.contracts.facts import CoachReply, FactsPacket
from backend.contracts.llm import CredentialSummary, LlmSelection
from backend.contracts.memory import MemoryHit
from backend.contracts.session import Intent, SessionBudget, SessionPlan
from backend.contracts.trial import TrialEvent
from backend.contracts.twin import ForecastBand, LifeContextWindow, TwinSnapshot
from backend.generation.blocks import CustomGameContent
from backend.registry.models import Battery, Dimension, Game, LlmProvider

OUT = Path("contracts")

CONTRACT_MODELS: list[type[BaseModel]] = [
    TrialEvent,
    ExerciseSpec,
    RoundResult,
    TwinSnapshot,
    ForecastBand,
    LifeContextWindow,
    Decision,
    FactsPacket,
    CoachReply,
    AcsEvent,
    AffectReading,
    BehaviourSignals,
    BiometricCues,
    MemoryHit,
    Intent,
    SessionBudget,
    SessionPlan,
    LlmSelection,
    CredentialSummary,
    CustomGameContent,
]

REF = "#/components/schemas/{model}"


def build_openapi() -> dict[str, Any]:
    spec = app.openapi()
    schemas: dict[str, Any] = spec.setdefault("components", {}).setdefault("schemas", {})
    _, defs = models_json_schema([(m, "serialization") for m in CONTRACT_MODELS], ref_template=REF)
    for name, schema in defs.get("$defs", {}).items():
        schemas.setdefault(name, schema)
    event_schema = TypeAdapter(Event).json_schema(mode="serialization", ref_template=REF)
    for name, schema in event_schema.pop("$defs", {}).items():
        schemas.setdefault(name, schema)
    schemas["Event"] = event_schema
    return spec


def build_registry_schemas() -> dict[str, dict[str, Any]]:
    def array_of(model: type[BaseModel]) -> dict[str, Any]:
        return TypeAdapter(list[model]).json_schema()  # type: ignore[valid-type]

    return {
        "dimensions.schema.json": array_of(Dimension),
        "game.schema.json": Game.model_json_schema(),
        "llm_providers.schema.json": array_of(LlmProvider),
        "batteries.schema.json": TypeAdapter(dict[str, Battery]).json_schema(),
    }


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    _write(OUT / "openapi.json", build_openapi())
    for name, schema in build_registry_schemas().items():
        _write(OUT / "registry" / name, schema)
    # LodestarState is internal to the backend; checking it builds a schema catches typos early.
    LodestarState.model_json_schema()
    print(f"contracts written to {OUT}/")


if __name__ == "__main__":
    main()
