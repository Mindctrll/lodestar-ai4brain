"""Shared building blocks for every contract model."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    """Base for data that crosses a boundary (API, events, graph state). Immutable, no extras."""

    model_config = ConfigDict(frozen=True, extra="forbid")


Probability = Annotated[float, Field(ge=0.0, le=1.0)]
Level = Annotated[float, Field(ge=0.0, le=1.0, description="Difficulty level, 0 easy to 1 hard")]
Milliseconds = Annotated[float, Field(ge=0.0)]

# Registry ids. Their existence is checked against the registry at runtime, not in the type.
DimensionId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
GameId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]

Persona = Literal["zitouna", "barq", "hikma", "sahbi"]
Trigger = Literal["voice", "ui", "cli", "schedule", "proactive"]
SuccessMode = Literal["chill", "balanced", "push"]
ConsentSwitch = Literal[
    "core",
    "cloud_ai",
    "microphone",
    "camera",
    "voice_tone",
    "deliberate_mistakes",
    "research_export",
]
PlayMode = Literal["assess", "train"]
ProviderId = Literal[
    "anthropic",
    "openai",
    "gemini",
    "deepseek",
    "xai",
    "mistral",
    "groq",
    "openrouter",
    "ollama",
    "stub",
]
