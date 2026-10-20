"""Check a coach draft against its facts packet before anything is shown (docs/plan/09).

WP2.4 extends this (forecast ranges, persona style rules, repair prompts); the core rules are
here from the start: every claim cites a known fact, every number appears in a cited fact, and
no banned clinical word gets through.
"""

import re
from dataclasses import dataclass, field

from backend.coach.language import find_banned
from backend.contracts.facts import FactsPacket

_CITE = re.compile(r"\[([FDKM]\d+)\]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
# "Nice work! [F1]" cites the sentence before it: move trailing citations inside the punctuation.
_TRAILING_CITES = re.compile(r"([.!?]+)\s*((?:\[[FDKM]\d+\]\s*)+)")


def sentences(text: str) -> list[str]:
    normalised = _TRAILING_CITES.sub(lambda m: " " + m.group(2).strip() + m.group(1) + " ", text)
    return [s.strip() for s in _SENTENCE.split(normalised.strip()) if s.strip()]


@dataclass
class Verdict:
    ok: bool
    violations: list[str] = field(default_factory=list)
    cited: list[str] = field(default_factory=list)


def verify(text: str, packet: FactsPacket, skill_names: list[str] | None = None) -> Verdict:
    violations: list[str] = []
    cited: list[str] = []
    known = set(packet.ids())
    names = [n.lower() for n in skill_names or []]
    for sentence in sentences(text):
        ids = _CITE.findall(sentence)
        unknown = [i for i in ids if i not in known]
        if unknown:
            violations.append(f"unknown fact ids {unknown}: {sentence!r}")
        cited.extend(i for i in ids if i in known)
        bare = _CITE.sub("", sentence)
        numbers = _NUMBER.findall(bare)
        makes_claim = bool(numbers) or any(n in bare.lower() for n in names)
        if makes_claim and not ids:
            violations.append(f"uncited claim: {sentence!r}")
        cited_text = " ".join(packet.text_of(i) or "" for i in ids)
        for number in numbers:
            if not re.search(rf"(?<![\d.]){re.escape(number)}(?![\d])", cited_text):
                violations.append(f"number {number} not in cited facts: {sentence!r}")
    for banned in find_banned(text):
        violations.append(f"banned word '{banned.word}'")
    return Verdict(not violations, violations, list(dict.fromkeys(cited)))
