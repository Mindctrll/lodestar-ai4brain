"""AI Collaboration Score observations (docs/plan/11)."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime

from backend.contracts.common import Contract

AcsComponent = Literal["V", "A", "I", "C", "R"]

ACS_COMPONENT_NAMES: dict[AcsComponent, str] = {
    "V": "Critical verification",
    "A": "Autonomy",
    "I": "Iteration",
    "C": "Clarification",
    "R": "Responsible use",
}


class AcsEvent(Contract):
    """One opportunity for a component; `success` says whether the user took it well."""

    component: AcsComponent
    success: bool
    source: str
    round_id: UUID | None = None
    ts: AwareDatetime
