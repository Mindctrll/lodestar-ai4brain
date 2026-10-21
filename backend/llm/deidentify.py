"""De-identified facts for cloud AI (docs/plan/14): before a message leaves for a hosted
provider, the user's name, email addresses, phone numbers and ids are replaced. Facts packets
already hold no raw events; this also covers what users type into memories and chat."""

import re
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d ()-]{6,}\d(?![\w.])")
_NAME_INTRO = re.compile(r"\b(my name is|i'?m called|call me)\s+([A-Z][\w'-]+)", re.I)


def scrub(text: str, names: Sequence[str] = ()) -> str:
    out = _EMAIL.sub("[email]", text)
    out = _UUID.sub("[id]", out)
    out = _PHONE.sub("[phone]", out)
    out = _NAME_INTRO.sub(lambda m: f"{m.group(1)} [name]", out)
    for name in names:
        if name and len(name) >= 2:
            out = re.sub(
                rf"\b{re.escape(name)}\b",
                lambda m: "The user" if m.group(0)[0].isupper() else "the user",
                out,
                flags=re.I,
            )
    return out


def scrub_messages(messages: Sequence[BaseMessage], names: Sequence[str] = ()) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in messages:
        if isinstance(m.content, str):
            out.append(m.model_copy(update={"content": scrub(m.content, names)}))
        else:
            out.append(m)
    return out
