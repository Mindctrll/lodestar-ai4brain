"""Recorded-response contract tests: each hosted adapter talks to a local fake that answers in
that provider's format (Done-when for WP1.4)."""

import base64
import logging
import os
from uuid import uuid4

import httpx
import pytest
from cryptography.exceptions import InvalidTag

from backend.llm.providers import KeyRejected, build_chat_model, list_models
from backend.llm.redaction import REDACTED, install, redact, register_secret, scrub
from backend.llm.vault import Vault
from backend.registry.loader import load_registry
from tests.backend.llm.fake_provider import REPLY, fake_provider

REGISTRY = load_registry()
KEY = "sk-test-0123456789abcdef"

# Path prefix each SDK expects in its base URL.
BASE_SUFFIX = {
    "anthropic": "",
    "openai": "/v1",
    "openrouter": "/api/v1",
    "deepseek": "/v1",
    "xai": "/v1",
    "mistral": "/v1",
    "groq": "",
    "gemini": "",
}
# Where each provider expects the key.
AUTH_HEADER = {"anthropic": "x-api-key", "gemini": "x-goog-api-key"}


@pytest.mark.parametrize("provider_id", sorted(BASE_SUFFIX))
async def test_hosted_adapter_round_trip(provider_id: str) -> None:
    provider = REGISTRY.provider(provider_id)
    with fake_provider() as fake:
        chat = build_chat_model(provider, "m", KEY, fake.base + BASE_SUFFIX[provider_id])
        reply = await chat.ainvoke("Say hello")
        assert reply.text == REPLY
        [request] = [r for r in fake.requests if r.method == "POST"]
        header = AUTH_HEADER.get(provider_id, "authorization")
        assert KEY in request.headers[header]


async def test_local_ollama_round_trip() -> None:
    with fake_provider() as fake:
        chat = build_chat_model(REGISTRY.provider("ollama"), "qwen3.5:4b", None, fake.base)
        assert (await chat.ainvoke("hi")).text == REPLY


@pytest.mark.parametrize(
    ("provider_id", "suffix", "expected"),
    [
        ("anthropic", "", ["m", "m-large"]),
        ("openai", "/v1", ["m", "m-large"]),
        ("gemini", "/v1beta", ["m"]),
        ("groq", "/openai/v1", ["m", "m-large"]),
        ("ollama", "", ["qwen3.5:4b"]),
    ],
)
async def test_key_check_lists_models_without_spending_tokens(
    provider_id: str, suffix: str, expected: list[str]
) -> None:
    provider = REGISTRY.provider(provider_id)
    with fake_provider() as fake:
        async with httpx.AsyncClient() as client:
            assert await list_models(provider, KEY, fake.base + suffix, client) == expected
        assert all(r.method == "GET" for r in fake.requests)
        assert all("key=" not in r.path for r in fake.requests)  # never in the URL


async def test_rejected_key_raises() -> None:
    with fake_provider() as fake:
        fake.reject_keys = True
        async with httpx.AsyncClient() as client:
            with pytest.raises(KeyRejected):
                await list_models(REGISTRY.provider("openai"), KEY, fake.base + "/v1", client)


def test_vault_round_trip_and_binding() -> None:
    vault = Vault(base64.b64encode(os.urandom(32)).decode())
    user = uuid4()
    sealed = vault.seal(user, "gemini", "AIzaSyExampleExampleExample123")
    assert sealed.last4 == "e123"
    assert b"AIza" not in sealed.ciphertext
    assert vault.open(user, "gemini", sealed.ciphertext, sealed.nonce).startswith("AIza")
    with pytest.raises(InvalidTag):  # can't move a sealed key to another account or provider
        vault.open(uuid4(), "gemini", sealed.ciphertext, sealed.nonce)
    with pytest.raises(InvalidTag):
        vault.open(user, "openai", sealed.ciphertext, sealed.nonce)
    assert not Vault(None).available


def test_redaction_masks_registered_and_known_shapes(caplog: pytest.LogCaptureFixture) -> None:
    install()
    secret = "custom-secret-value-123456"
    register_secret(secret)
    log = logging.getLogger("najma.test")
    with caplog.at_level(logging.INFO):
        log.info("calling with %s and sk-abcdefghijklmnop and Bearer abc.def.ghi123", secret)
        try:
            raise ValueError(f"bad key {secret}")
        except ValueError:
            log.exception("boom")
    text = caplog.text
    assert secret not in text and "sk-abcdefghijklmnop" not in text and "abc.def.ghi123" not in text
    assert REDACTED in text
    assert REDACTED in redact("x-goog-api-key: AIzaSy0123456789012345678901")
    assert scrub({"a": [secret]}) == {"a": [REDACTED]}


def test_redaction_keeps_record_args_shape() -> None:
    """uvicorn's access formatter unpacks record.args, so redaction must keep the tuple."""
    install()
    record = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/health?token=abcdefgh12345678", "1.1", 200), None,
    )  # fmt: skip
    assert isinstance(record.args, tuple) and len(record.args) == 5 and record.args[4] == 200
    assert "abcdefgh12345678" not in record.getMessage()
