"""Check a coach draft against its facts packet before anything is shown (docs/plan/09):

1. every sentence that makes a claim cites at least one known fact id,
2. every number appears in a cited fact,
3. no forecast is stated as a certainty (it must carry a range),
4. the clinical-language filter passes,
5. the persona's style rules pass.
"""

import re
from dataclasses import dataclass, field

from backend.coach.language import find_banned
from backend.contracts.common import Persona
from backend.contracts.facts import FactsPacket

_CITE = re.compile(r"\[([FDKM]\d+)\]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
# "Nice work! [F1]" cites the sentence before it: move trailing citations inside the punctuation.
_TRAILING_CITES = re.compile(r"([.!?]+)\s*((?:\[[FDKM]\d+\]\s*)+)")
_FORECAST = re.compile(
    r"\b(will (reach|be|get|hit|improve|rise|go)|you'll (reach|be|get)|expect(ed)?|"
    r"forecast|predict(ed)?|on track to)\b",
    re.IGNORECASE,
)
_RANGE = re.compile(r"\d+\s*%?\s*(?:-|\u2013|to)\s*\d+|\bbetween\s+\d+|\blikely\b", re.IGNORECASE)

MAX_SENTENCES = 6
MAX_CHARS = 700
# Persona style rules (docs/plan/09, "Personas"). They change how Lodestar talks, not what it says.
STYLE_RULES: dict[str, dict[str, float]] = {
    "willow": {"max_sentences": 4},
    "spark": {"max_words_per_sentence": 14},
    "sage": {"no_exclamations": 1},
    "buddy": {"max_sentences": 5},
}


def sentences(text: str) -> list[str]:
    normalised = _TRAILING_CITES.sub(lambda m: " " + m.group(2).strip() + m.group(1) + " ", text)
    return [s.strip() for s in _SENTENCE.split(normalised.strip()) if s.strip()]


@dataclass
class Verdict:
    ok: bool
    violations: list[str] = field(default_factory=list)
    cited: list[str] = field(default_factory=list)


def style_violations(text: str, persona: Persona | None) -> list[str]:
    parts = sentences(text)
    out = []
    if len(parts) > MAX_SENTENCES or len(text) > MAX_CHARS:
        out.append(f"too long: {len(parts)} sentences, {len(text)} characters")
    rules = STYLE_RULES.get(persona or "", {})
    if "max_sentences" in rules and len(parts) > rules["max_sentences"]:
        out.append(f"{persona} uses at most {int(rules['max_sentences'])} sentences")
    if "max_words_per_sentence" in rules and parts:
        words = sum(len(_CITE.sub("", s).split()) for s in parts) / len(parts)
        if words > rules["max_words_per_sentence"]:
            out.append(f"{persona} keeps sentences short (average {words:.0f} words)")
    if rules.get("no_exclamations") and "!" in text:
        out.append(f"{persona} doesn't use exclamation marks")
    return out


def verify(
    text: str,
    packet: FactsPacket,
    skill_names: list[str] | None = None,
    persona: Persona | None = None,
) -> Verdict:
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
        if _FORECAST.search(bare) and numbers and not _RANGE.search(bare):
            violations.append(f"forecast stated without its range: {sentence!r}")
    for banned in find_banned(text):
        violations.append(f"banned word '{banned.word}'")
    violations += style_violations(text, persona)
    return Verdict(not violations, violations, list(dict.fromkeys(cited)))
