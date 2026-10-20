"""LLM selection. Never holds a key (AGENTS.md rule 9)."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from backend.contracts.common import Contract, ProviderId

LlmMode = Literal["hosted", "local", "stub"]


class LlmSelection(Contract):
    mode: LlmMode
    provider: ProviderId
    model: str = Field(min_length=1)
    credential_id: UUID | None = Field(
        default=None, description="Points at app.llm_credentials; the key itself never travels"
    )


class CredentialSummary(Contract):
    """What the API and the export show about a saved key."""

    provider: ProviderId
    key_last4: str = Field(min_length=4, max_length=4)
    status: Literal["ok", "rejected", "out_of_credit", "unchecked"]
