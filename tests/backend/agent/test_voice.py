"""WP2.10 voice basics: private speech to text from a recorded fixture, and UW4 underneath
("give me a memory game about football" starts Market List with football words)."""

import importlib.util
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.agent.context import Services
from backend.api import voice
from backend.api.deps import engine_dep
from backend.api.main import create_app
from backend.config import get_settings
from backend.generation.pipeline import ContentService
from backend.generation.vocab import word_theme
from backend.llm.factory import LlmFactory
from backend.registry.loader import load_registry
from tests.backend.agent.conftest import RunnerFactory, test_settings
from tests.backend.agent.test_graph import collect, interrupt_of
from tests.backend.agent.test_policy import returning_user

REGISTRY = load_registry()
FIXTURES = Path(__file__).parents[2] / "fixtures" / "voice"
HAS_WHISPER = importlib.util.find_spec("faster_whisper") is not None


@pytest.fixture
def app(aengine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    application = create_app(with_lifespan=False)
    application.state.services = Services(
        engine=aengine, registry=REGISTRY, llm=LlmFactory(REGISTRY, test_settings(), aengine)
    )
    application.dependency_overrides[engine_dep] = lambda: aengine
    small = get_settings().model_copy(update={"whisper_model": "tiny.en"})  # fast in tests
    monkeypatch.setattr(voice, "get_settings", lambda: small)
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def signup(client: httpx.AsyncClient, **consent: bool) -> dict[str, str]:
    created = (await client.post("/users", json={"age_confirmed": True, "consent": consent})).json()
    return {"Authorization": f"Bearer {created['token']}"}


async def test_transcribe_needs_the_microphone_switch_and_a_wav(
    client: httpx.AsyncClient,
) -> None:
    headers = await signup(client)
    wav = (FIXTURES / "i_slept_badly.wav").read_bytes()
    refused = await client.post("/voice/transcribe", content=wav, headers=headers)
    assert refused.status_code == 409
    await client.put("/consent/microphone", json={"granted": True}, headers=headers)
    bad = await client.post("/voice/transcribe", content=b"not audio", headers=headers)
    assert bad.status_code == 422


@pytest.mark.skipif(not HAS_WHISPER, reason="needs the whisper extra (uv sync --extra whisper)")
async def test_private_voice_round_trip_from_a_recording(client: httpx.AsyncClient) -> None:
    headers = await signup(client, microphone=True)
    for name, said in (
        ("give_me_a_memory_game_about_football", "give me a memory game about football"),
        ("i_slept_badly", "i slept like four hours"),
    ):
        wav = (FIXTURES / f"{name}.wav").read_bytes()
        reply = await client.post("/voice/transcribe", content=wav, headers=headers)
        assert reply.status_code == 200, reply.text
        text = reply.json()["text"].lower().strip(" .")
        assert text == said and reply.json()["engine"] == "whisper:tiny.en"


async def test_uw4_memory_game_about_football(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    runner = await make_runner()
    runner.services = replace(runner.services, content=ContentService(aengine, llm=None))
    user_id = await returning_user(aengine)
    session_id = await runner.create_session(user_id, "voice")
    events = await collect(
        runner, user_id, session_id, message="Give me a memory game about football."
    )
    spec = interrupt_of(events)
    assert spec["game_id"] == "market_list" and spec["mode"] == "train"
    assert spec["content"]["theme"] == "football"
    football = set(word_theme("football") or [])
    assert all(w in football for words in spec["content"]["lists"] for w in words)
    [plan] = [e for e in events if e["kind"] == "decision" and e["node"] == "plan_next"]
    assert plan["reason"] == "Football memory, coming up: Market List."
