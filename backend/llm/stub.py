"""A deterministic chat model for tests and the simulator (docs/plan/03, principle 5)."""

import re
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

Responder = Callable[[Sequence[BaseMessage]], str]

_FACT = re.compile(r"^\s*\[?([FDKM]\d+)\]?[:\s]+(.+)$", re.MULTILINE)


def default_responder(messages: Sequence[BaseMessage]) -> str:
    """Repeat the first fact it was given, citing it, so coach tests have a valid draft."""
    text = "\n".join(str(m.content) for m in messages)
    match = _FACT.search(text)
    if match:
        return f"{match.group(2).strip().rstrip('.')} [{match.group(1)}]."
    return "Okay."


class StubFailure(RuntimeError):
    pass


class StubChatModel(BaseChatModel):
    responder: Responder = default_responder
    fail: bool = False

    @property
    def _llm_type(self) -> str:
        return "lodestar-stub"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.fail:
            raise StubFailure("stub model set to fail")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(self.responder(messages)))])
