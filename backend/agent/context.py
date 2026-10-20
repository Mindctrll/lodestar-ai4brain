"""Run-scoped context (docs/plan/03, State). Not checkpointed; rebuilt by the runner each run.

It holds the LLM selection (provider, model, credential id; never a key), consent flags, the seed
and the services nodes need.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from backend.contracts.llm import LlmSelection
from backend.llm.factory import LlmFactory
from backend.registry.models import Registry
from backend.scoring.norms import Norms


@dataclass(frozen=True)
class Services:
    engine: AsyncEngine
    registry: Registry
    llm: LlmFactory
    norms: Norms = field(default_factory=Norms)
    memory: Any | None = None  # QdrantStore, from WP1.5


@dataclass(frozen=True)
class NajmaContext:
    user_id: UUID
    session_id: UUID
    llm: LlmSelection
    consent: frozenset[str]
    services: Services
    seed: int = 0
