"""Recall results from Qdrant (docs/plan/04)."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from backend.contracts.common import Contract, Probability


class MemoryHit(Contract):
    point_id: UUID
    collection: Literal["episodic", "facts"]
    text: str
    score: float
    created_at: AwareDatetime
    importance: Probability
    source_event_ids: list[UUID] = Field(default_factory=list)
