"""Private voice: speech to text on this server (docs/plan/12, Voice stack).

The browser's own speech recognition may send audio to its maker; this endpoint is the private
alternative. The browser sends 16 kHz mono 16-bit WAV (it converts with Web Audio, so the server
needs no audio codecs). The audio is held in memory only for the transcription and never stored
(docs/plan/14, Retention). It needs the microphone consent switch.
"""

import asyncio
import io
import logging
import wave
from functools import lru_cache
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Request, status

from backend.api.deps import CurrentUser, Engine, RegistryDep
from backend.config import get_settings
from backend.contracts.common import Contract
from backend.db.consent_store import granted_switches

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])

RATE = 16_000
MAX_SECONDS = 30
MAX_BYTES = RATE * 2 * MAX_SECONDS + 1024


class Transcript(Contract):
    text: str
    engine: str
    seconds: float


@lru_cache(maxsize=1)
def _model(name: str) -> Any:
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]  # optional extra

    return WhisperModel(name, device="cpu", compute_type="int8")


def samples(wav: bytes) -> np.ndarray:
    try:
        with wave.open(io.BytesIO(wav)) as w:
            if w.getframerate() != RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError("expected 16 kHz mono 16-bit WAV")
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise ValueError("not a WAV file") from exc
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(audio: np.ndarray, model_name: str) -> str:
    segments, _ = _model(model_name).transcribe(audio, language="en", beam_size=1)
    return " ".join(s.text.strip() for s in segments).strip()


@router.post("/transcribe", response_model=Transcript)
async def post_transcribe(
    request: Request, user_id: CurrentUser, engine: Engine, registry: RegistryDep
) -> Transcript:
    async with engine.connect() as conn:
        consent = await granted_switches(conn, user_id, registry.consent)
    if "microphone" not in consent:
        raise HTTPException(status.HTTP_409_CONFLICT, "Turn on the microphone switch first.")
    body = await request.body()
    if len(body) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Keep it under 30 seconds.")
    try:
        audio = samples(body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    del body  # the recording itself is not kept
    model = get_settings().whisper_model
    try:
        text = await asyncio.to_thread(transcribe, audio, model)
    except ImportError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Private voice isn't set up on this server."
        ) from exc
    return Transcript(text=text, engine=f"whisper:{model}", seconds=round(len(audio) / RATE, 2))
