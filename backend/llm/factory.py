"""The one door to LLMs (docs/plan/03, "LLM providers" and the reliability ladder).

`generate` walks the ladder: the user's hosted provider (with their key) -> local Ollama ->
`NoModelAvailable`, at which point the caller uses a fixed template. Every step down is reported
in `degraded`. Keys are decrypted here, in memory, for one call; they never leave this module.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeVar
from uuid import UUID

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.config import Settings
from backend.contracts.llm import LlmSelection
from backend.db.llm_store import get_credential, set_credential_status
from backend.llm.providers import build_chat_model
from backend.llm.stub import Responder, StubChatModel
from backend.llm.vault import Vault
from backend.registry.models import Registry

log = logging.getLogger(__name__)

# An interactive call that takes longer than this falls to the next rung (Ollama, then a template).
CALL_TIMEOUT_S = 30.0

M = TypeVar("M", bound=BaseModel)


class NoModelAvailable(RuntimeError):
    def __init__(self, degraded: Sequence[str]) -> None:
        super().__init__("no LLM available; use a template")
        self.degraded = list(degraded)


@dataclass(frozen=True)
class LlmReply:
    text: str
    provider: str
    model: str
    degraded: tuple[str, ...]


@dataclass(frozen=True)
class StructuredReply[T]:
    value: T
    provider: str
    model: str
    degraded: tuple[str, ...]


@dataclass(frozen=True)
class _Rung:
    provider: str
    model: str
    chat: BaseChatModel


def _status_for(exc: BaseException) -> str | None:
    """Map a provider error to a credential status, when it's about the key."""
    code = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    name = type(exc).__name__
    if code in (401, 403) or "Authentication" in name or "PermissionDenied" in name:
        return "rejected"
    if code == 402:
        return "out_of_credit"
    return None


class LlmFactory:
    def __init__(
        self,
        registry: Registry,
        settings: Settings,
        engine: AsyncEngine,
        *,
        base_overrides: dict[str, str] | None = None,
        stub_responder: Responder | None = None,
        call_timeout_s: float = CALL_TIMEOUT_S,
    ) -> None:
        self.call_timeout_s = call_timeout_s
        self.registry = registry
        self.settings = settings
        self.engine = engine
        self.vault = Vault(settings.master_key.get_secret_value() if settings.master_key else None)
        self.base_overrides = base_overrides or {}
        self.stub_responder = stub_responder

    def base_for(self, provider_id: str) -> str | None:
        if provider_id in self.base_overrides:
            return self.base_overrides[provider_id]
        if provider_id == "ollama":
            return self.settings.ollama_url
        return None

    def api_base(self, provider_id: str) -> str:
        """Root used for model listing; overrides win (tests)."""
        override = self.base_overrides.get(provider_id)
        if override:
            return override
        if provider_id == "ollama":
            return self.settings.ollama_url
        base = self.registry.provider(provider_id).api_base
        if base is None:
            raise ValueError(f"{provider_id} has no api_base")
        return str(base)

    def _stub(self) -> _Rung:
        chat = (
            StubChatModel(responder=self.stub_responder) if self.stub_responder else StubChatModel()
        )
        return _Rung("stub", "stub", chat)

    def _local(self) -> _Rung:
        provider = self.registry.provider("ollama")
        chat = build_chat_model(provider, self.settings.local_model, None, self.base_for("ollama"))
        return _Rung("ollama", self.settings.local_model, chat)

    async def _ladder(self, user_id: UUID, selection: LlmSelection) -> list[_Rung]:
        if selection.mode == "stub":
            return [self._stub()]
        rungs: list[_Rung] = []
        if selection.mode == "hosted" and self.vault.available:
            async with self.engine.connect() as conn:
                stored = await get_credential(conn, user_id, selection.provider)
            if stored is not None and stored.status != "rejected":
                key = self.vault.open(user_id, selection.provider, stored.ciphertext, stored.nonce)
                provider = self.registry.provider(selection.provider)
                chat = build_chat_model(provider, selection.model, key, self.base_for(provider.id))
                rungs.append(_Rung(provider.id, selection.model, chat))
        rungs.append(self._local())
        return rungs

    async def _walk(
        self, user_id: UUID, selection: LlmSelection, call: Any
    ) -> tuple[Any, _Rung, tuple[str, ...]]:
        rungs = await self._ladder(user_id, selection)
        first = selection.provider if selection.mode != "local" else "ollama"
        degraded: list[str] = []
        if selection.mode == "hosted" and rungs[0].provider != selection.provider:
            degraded.append(f"llm:{selection.provider}->{rungs[0].provider}")
        for rung in rungs:
            try:
                result = await asyncio.wait_for(call(rung), self.call_timeout_s)
                return result, rung, tuple(degraded)
            except Exception as exc:
                log.warning("LLM call failed on %s: %s", rung.provider, type(exc).__name__)
                status = _status_for(exc)
                if status and rung.provider not in ("ollama", "stub"):
                    async with self.engine.begin() as conn:
                        await set_credential_status(conn, user_id, rung.provider, status)
                nxt = rungs[rungs.index(rung) + 1].provider if rung is not rungs[-1] else "template"
                step = f"llm:{rung.provider}->{nxt}"
                if step not in degraded:
                    degraded.append(step)
        if not degraded:
            degraded.append(f"llm:{first}->template")
        raise NoModelAvailable(degraded)

    async def generate(
        self, user_id: UUID, selection: LlmSelection, messages: Sequence[BaseMessage]
    ) -> LlmReply:
        async def call(rung: _Rung) -> str:
            reply = await rung.chat.ainvoke(list(messages))
            return reply.text if hasattr(reply, "text") else str(reply.content)

        text, rung, degraded = await self._walk(user_id, selection, call)
        return LlmReply(text, rung.provider, rung.model, degraded)

    async def structured(
        self,
        user_id: UUID,
        selection: LlmSelection,
        messages: Sequence[BaseMessage],
        schema: type[M],
    ) -> StructuredReply[M]:
        async def call(rung: _Rung) -> M:
            if rung.provider == "stub":
                reply = await rung.chat.ainvoke(list(messages))
                return schema.model_validate_json(str(reply.content))
            caps = self.registry.provider(rung.provider).capabilities
            method = caps.structured_method
            runnable = rung.chat.with_structured_output(schema, method=method)
            value = await runnable.ainvoke(list(messages))
            return value if isinstance(value, schema) else schema.model_validate(value)

        value, rung, degraded = await self._walk(user_id, selection, call)
        return StructuredReply(value, rung.provider, rung.model, degraded)
