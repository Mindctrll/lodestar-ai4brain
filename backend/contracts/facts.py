"""Facts packets: the coach can only say what the data shows (docs/plan/09)."""

from typing import Annotated

from pydantic import Field, model_validator

from backend.contracts.common import Contract, DimensionId, Persona

FactId = Annotated[str, Field(pattern=r"^[FD]\d+$")]
KnowledgeId = Annotated[str, Field(pattern=r"^K\d+$")]
MemoryId = Annotated[str, Field(pattern=r"^M\d+$")]


class Fact(Contract):
    id: FactId
    text: str = Field(min_length=1)
    dim: DimensionId | None = None
    events: list[str] = Field(default_factory=list)
    decision: bool = False


class KnowledgeItem(Contract):
    id: KnowledgeId
    text: str = Field(min_length=1)
    source: str
    evidence_level: str | None = None


class MemoryItem(Contract):
    id: MemoryId
    text: str = Field(min_length=1)


class FactsPacket(Contract):
    facts: list[Fact] = Field(default_factory=list)
    knowledge: list[KnowledgeItem] = Field(default_factory=list)
    memories: list[MemoryItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> FactsPacket:
        ids = self.ids()
        if len(ids) != len(set(ids)):
            raise ValueError("facts packet ids must be unique")
        return self

    def ids(self) -> list[str]:
        return [
            *(f.id for f in self.facts),
            *(k.id for k in self.knowledge),
            *(m.id for m in self.memories),
        ]

    def text_of(self, item_id: str) -> str | None:
        items: list[Fact | KnowledgeItem | MemoryItem] = [
            *self.facts,
            *self.knowledge,
            *self.memories,
        ]
        return next((item.text for item in items if item.id == item_id), None)


class CoachReply(Contract):
    text: str
    cited_ids: list[str]
    persona: Persona
    first_draft_passed: bool
    repairs: int = Field(ge=0, le=2)
    used_template: bool
