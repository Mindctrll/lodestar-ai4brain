"""Runtime settings, read once from the environment.

Secrets (the master key, the operator's LLM key) are kept as `SecretStr` so they
never show up in reprs or logs (AGENTS.md rule 9).
"""

import os
from functools import lru_cache

from pydantic import BaseModel, SecretStr


class Settings(BaseModel, frozen=True):
    database_url: str
    qdrant_url: str
    ollama_url: str
    local_model: str
    master_key: SecretStr | None
    operator_llm_provider: str | None
    operator_llm_key: SecretStr | None
    operator_llm_model: str | None
    memory_dir: str
    registry_dir: str


def _optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _optional_secret(name: str) -> SecretStr | None:
    value = _optional(name)
    return SecretStr(value) if value else None


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql://najma:najma@localhost:5442/najma"
        ),
        qdrant_url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        local_model=os.environ.get("NAJMA_LOCAL_MODEL", "qwen3.5:4b"),
        master_key=_optional_secret("NAJMA_MASTER_KEY"),
        operator_llm_provider=_optional("NAJMA_OPERATOR_LLM_PROVIDER"),
        operator_llm_key=_optional_secret("NAJMA_OPERATOR_LLM_KEY"),
        operator_llm_model=_optional("NAJMA_OPERATOR_LLM_MODEL"),
        memory_dir=os.environ.get("NAJMA_MEMORY_DIR", "memory"),
        registry_dir=os.environ.get("NAJMA_REGISTRY_DIR", "registry"),
    )
