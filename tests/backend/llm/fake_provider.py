"""A local HTTP server that answers like each LLM provider, with recorded response shapes.

Every request is kept, so tests can check which header carried the key.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

REPLY = "Hello from the fake provider"

ANTHROPIC_MESSAGE = {
    "id": "msg_01", "type": "message", "role": "assistant", "model": "m",
    "content": [{"type": "text", "text": REPLY}], "stop_reason": "end_turn",
    "stop_sequence": None, "usage": {"input_tokens": 5, "output_tokens": 3},
}  # fmt: skip
OPENAI_COMPLETION = {
    "id": "chatcmpl-1", "object": "chat.completion", "created": 1760000000, "model": "m",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": REPLY},
                 "finish_reason": "stop", "logprobs": None}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
}  # fmt: skip
GEMINI_RESPONSE = {
    "candidates": [{"content": {"role": "model", "parts": [{"text": REPLY}]},
                    "finishReason": "STOP", "index": 0}],
    "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3, "totalTokenCount": 8},
    "modelVersion": "m",
}  # fmt: skip
OLLAMA_CHAT = {
    "model": "m", "created_at": "2026-10-21T00:00:00Z",
    "message": {"role": "assistant", "content": REPLY}, "done": True, "done_reason": "stop",
    "total_duration": 1, "load_duration": 1, "prompt_eval_count": 5, "prompt_eval_duration": 1,
    "eval_count": 3, "eval_duration": 1,
}  # fmt: skip


@dataclass
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: Any


@dataclass
class FakeProvider:
    base: str
    requests: list[Recorded] = field(default_factory=list)
    reject_keys: bool = False


def _route(method: str, path: str) -> tuple[int, Any]:
    path = path.split("?", 1)[0]
    if method == "GET":
        if path.endswith("/api/tags"):
            return 200, {"models": [{"name": "qwen3.5:4b"}]}
        if path.endswith("/models") and "v1beta" in path:
            chat = {"name": "models/m", "supportedGenerationMethods": ["generateContent"]}
            embed = {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}
            return 200, {"models": [chat, embed]}
        if path.endswith("/models"):
            return 200, {"data": [{"id": "m"}, {"id": "m-large"}]}
    if method == "POST":
        if path.endswith("/messages"):
            return 200, ANTHROPIC_MESSAGE
        if path.endswith("/chat/completions"):
            return 200, OPENAI_COMPLETION
        if ":generateContent" in path:
            return 200, GEMINI_RESPONSE
        if path.endswith("/api/chat"):
            return 200, OLLAMA_CHAT
    return 404, {"error": f"no route for {method} {path}"}


@contextmanager
def fake_provider() -> Iterator[FakeProvider]:
    state: FakeProvider

    class Handler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = raw.decode(errors="replace")
            state.requests.append(
                Recorded(
                    self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body
                )
            )
            code, payload = (
                (401, {"error": "invalid key"})
                if state.reject_keys
                else _route(self.command, self.path)
            )
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _handle

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state = FakeProvider(base=f"http://127.0.0.1:{server.server_address[1]}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
