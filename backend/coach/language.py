"""Clinical-language lexicon for user-facing text (docs/plan/09, AGENTS.md rule 2).

WP2.4 adds the LLM check and the red-team list on top of this lexicon.
"""

import re
from dataclasses import dataclass

# (pattern, suggested replacement). Patterns are matched case-insensitively on word boundaries.
BANNED: tuple[tuple[str, str], ...] = (
    (r"deficits?", "growth area"),
    (r"impairments?|impaired", "practice area"),
    (r"disorders?", "practice area"),
    (r"dysfunctions?|dysfunctional", "practice area"),
    (r"diagnos(?:is|es|e|ed|ing|tic)", "profile"),
    (r"symptoms?", "pattern"),
    (r"treatments?", "practice"),
    (r"therap(?:y|ies|eutic)", "practice"),
    (r"adhd", "(don't name conditions)"),
    (r"dementia|alzheimer'?s", "(don't name conditions)"),
    (r"dyslexi(?:a|c)|dyscalculia|dyspraxia", "(don't name conditions)"),
    (r"autis(?:m|tic)|asd|ocd|ptsd|bipolar|schizophreni(?:a|c)", "(don't name conditions)"),
    (r"depression|anxiety\s+disorder", "(don't name conditions)"),
    (r"iq", "skill estimate"),
    (r"brain\s+age|mental\s+age", "skill estimate"),
    (r"abnormal(?:ly)?", "outside the typical range"),
    (r"normal", "typical range"),
    (r"your\s+brain\s+is", "your results show"),
)

ALLOW_PRAGMA = "lint-language: allow"

_COMPILED = tuple(
    (re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE), replacement)
    for pattern, replacement in BANNED
)


@dataclass(frozen=True)
class Violation:
    word: str
    replacement: str
    line: int
    column: int


def find_banned(text: str) -> list[Violation]:
    """Return every banned word in `text`, skipping lines that carry the allow pragma."""
    violations: list[Violation] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if ALLOW_PRAGMA in line:
            continue
        for regex, replacement in _COMPILED:
            for match in regex.finditer(line):
                violations.append(
                    Violation(match.group(0), replacement, line_no, match.start() + 1)
                )
    return sorted(violations, key=lambda v: (v.line, v.column))
