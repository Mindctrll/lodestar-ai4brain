"""Build LangChain chat models from the provider registry and check keys (docs/plan/03, "LLM
providers"). Nodes never call this directly; they go through `LlmFactory`."""

from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel

from backend.llm.stub import StubChatModel
from backend.registry.models import LlmProvider

TIMEOUT_S = 30.0


class KeyRejected(PermissionError):
    """The provider refused the key (401/403)."""


class OutOfCredit(PermissionError):
    """The provider says the account has no credit left (402)."""


class ProviderUnavailable(ConnectionError):
    pass


def build_chat_model(
    provider: LlmProvider, model: str, api_key: str | None, base_url: str | None = None
) -> BaseChatModel:
    """One LangChain chat model. `base_url` is only passed when overridden (tests, Ollama)."""
    kind = provider.integration
    common: dict[str, Any] = {"model": model}
    if base_url:
        common["base_url"] = base_url
    if kind == "stub":
        return StubChatModel()
    if kind == "langchain-ollama":
        from langchain_ollama import ChatOllama

        # No hidden reasoning (much faster on CPU) and a bounded reply length.
        return ChatOllama(
            reasoning=False,
            num_predict=900,
            client_kwargs={"timeout": TIMEOUT_S},
            **common,
        )
    if api_key is None:
        raise KeyRejected(f"{provider.name} needs an API key")
    if kind == "langchain-anthropic":
        from langchain_anthropic import ChatAnthropic

        # No sampling parameters: current Claude models reject them (registry capabilities).
        return ChatAnthropic(api_key=api_key, timeout=TIMEOUT_S, max_retries=1, **common)
    if kind == "langchain-openai":
        from langchain_openai import ChatOpenAI

        if provider.api_base and "base_url" not in common and provider.id != "openai":
            common["base_url"] = str(provider.api_base)  # OpenRouter
        return ChatOpenAI(api_key=api_key, timeout=TIMEOUT_S, max_retries=1, **common)
    if kind == "langchain-google-genai":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            api_key=api_key, request_timeout=TIMEOUT_S, retries=1, **common
        )
    if kind == "langchain-deepseek":
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(api_key=api_key, timeout=TIMEOUT_S, max_retries=1, **common)
    if kind == "langchain-xai":
        from langchain_xai import ChatXAI

        return ChatXAI(api_key=api_key, timeout=TIMEOUT_S, max_retries=1, **common)
    if kind == "langchain-mistralai":
        from langchain_mistralai import ChatMistralAI

        return ChatMistralAI(api_key=api_key, timeout=int(TIMEOUT_S), max_retries=1, **common)
    if kind == "langchain-groq":
        from langchain_groq import ChatGroq

        return ChatGroq(api_key=api_key, timeout=TIMEOUT_S, max_retries=1, **common)
    raise ValueError(f"unknown integration {kind}")


def _models_request(provider: LlmProvider, base: str, api_key: str | None) -> httpx.Request:
    base = base.rstrip("/")
    if provider.id == "anthropic":
        return httpx.Request(
            "GET",
            f"{base}/v1/models",
            headers={"x-api-key": api_key or "", "anthropic-version": "2023-06-01"},
        )
    if provider.id == "gemini":
        # Header, not the ?key= query parameter, so the key never lands in a logged URL.
        return httpx.Request("GET", f"{base}/models", headers={"x-goog-api-key": api_key or ""})
    if provider.id == "ollama":
        return httpx.Request("GET", f"{base}/api/tags")
    return httpx.Request("GET", f"{base}/models", headers={"Authorization": f"Bearer {api_key}"})


def _model_ids(provider: LlmProvider, body: Any) -> list[str]:
    if provider.id == "gemini":
        models = body.get("models", [])
        return [
            m["name"].removeprefix("models/")
            for m in models
            if "generateContent" in m.get("supportedGenerationMethods", ["generateContent"])
        ]
    if provider.id == "ollama":
        return [m["name"] for m in body.get("models", [])]
    return [m["id"] for m in body.get("data", [])]


async def list_models(
    provider: LlmProvider, api_key: str | None, base: str, client: httpx.AsyncClient
) -> list[str]:
    """The cheap test call made when a key is saved: list models, spend no tokens."""
    try:
        response = await client.send(
            _models_request(provider, base, api_key), follow_redirects=True
        )
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(f"{provider.name} could not be reached") from exc
    if response.status_code in (401, 403):
        raise KeyRejected(f"{provider.name} rejected the key")
    if response.status_code == 402:
        raise OutOfCredit(f"{provider.name} reports no credit left")
    if response.status_code >= 400:
        raise ProviderUnavailable(f"{provider.name} answered {response.status_code}")
    return sorted(_model_ids(provider, response.json()))
