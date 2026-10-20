"""Second line of defence for AGENTS.md rule 9: scrub API keys and tokens from every log record.

Keys seen by the vault are registered and replaced exactly; well-known key shapes and bearer
tokens are masked by pattern even if they were never registered.
"""

import logging
import re
import threading
from typing import Any

REDACTED = "[redacted]"

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),  # Anthropic, OpenAI, DeepSeek, OpenRouter
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google
    re.compile(r"xai-[A-Za-z0-9_\-]{8,}"),  # xAI
    re.compile(r"gsk_[A-Za-z0-9]{8,}"),  # Groq
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(
        r"(?i)((?:api[_-]?key|token|x-api-key|x-goog-api-key)[\"']?\s*[:=]\s*[\"']?)[^\s\"'&,]{8,}"
    ),
]

_secrets: set[str] = set()
_lock = threading.Lock()


def register_secret(secret: str) -> None:
    if len(secret) >= 8:
        with _lock:
            _secrets.add(secret)


def redact(text: str) -> str:
    with _lock:
        known = sorted(_secrets, key=len, reverse=True)
    for secret in known:
        text = text.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + REDACTED, text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


_installed = False


def install() -> None:
    """Redact every log record at creation, whichever logger or handler it goes to."""
    global _installed
    if _installed:
        return
    base_factory = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base_factory(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # a malformed log call must not break logging
            return record
        record.msg, record.args = redact(message), None
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return record

    logging.setLogRecordFactory(factory)
    _installed = True


def scrub(value: Any) -> Any:
    """Redact strings inside nested data before it goes into traces or events."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [scrub(v) for v in value]
    return value
