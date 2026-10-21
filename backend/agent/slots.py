"""Filling tool arguments from what the user said (WP2.11): dates, periods, life-context labels,
coach and mode names. Plain rules, so they work without a model and are easy to test.

Times are in the user's own time zone: "today" means their day, not the server's.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.contracts.common import Persona, SuccessMode
from backend.contracts.twin import LifeContextWindow

MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}  # fmt: skip
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
GOAL_DAYS_DEFAULT = 14

_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,9})\b", re.I)
_MONTH_DAY = re.compile(r"\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
_IN_N = re.compile(r"\bin (\d{1,3}|a|one|two|three|four) (day|week|month)s?\b", re.I)
_PAST_N = re.compile(r"\b(?:last|past) (\d{1,3}) (day|week|month)s?\b", re.I)
_WORD_N = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4}
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30}
# "±5", "+/- 5", "plus or minus 5", "within 5 points" (but not "within 2 weeks")
_TARGET = re.compile(
    r"(?:±|\+/-|\+-|plus or minus|within)\s*(\d{1,2})\b(?!\s*(?:day|week|month|year)s?\b)", re.I
)


def local_tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Africa/Tunis")
    except ValueError, KeyError:
        return ZoneInfo("Africa/Tunis")


def _explicit_date(text: str, today: date) -> date | None:
    for match in _DAY_MONTH.finditer(text):
        month = MONTHS.get(match.group(2).lower())
        if month:
            return _next_occurrence(today, month, int(match.group(1)))
    for match in _MONTH_DAY.finditer(text):
        month = MONTHS.get(match.group(1).lower())
        if month:
            return _next_occurrence(today, month, int(match.group(2)))
    return None


def _next_occurrence(today: date, month: int, day: int) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today:
            return d
    return None


def _weekday(text: str, today: date) -> date | None:
    lowered = text.lower()
    for i, name in enumerate(WEEKDAYS):
        if re.search(rf"\b{name}\b", lowered):
            ahead = (i - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
    return None


def due_date(text: str, today: date, exam_day: date | None = None) -> date:
    """When a goal is due: an explicit date, a weekday, "in 2 weeks", "next month", "end of the
    month", "before exams" (the exam period the user told Najma about), else two weeks."""
    lowered = text.lower()
    found = _explicit_date(lowered, today) or _weekday(lowered, today)
    if found:
        return found
    if m := _IN_N.search(lowered):
        n = _WORD_N.get(m.group(1)) or int(m.group(1))
        return today + timedelta(days=n * _UNIT_DAYS[m.group(2)])
    if re.search(r"\bnext week\b", lowered):
        return today + timedelta(days=7)
    if re.search(r"\bnext month\b", lowered):
        return today + timedelta(days=30)
    if re.search(r"\bend of (the |this )?month\b", lowered):
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt - timedelta(days=1)
    if re.search(r"\b(before|by) (my |the )?exams?\b", lowered) and exam_day and exam_day > today:
        return exam_day
    return today + timedelta(days=GOAL_DAYS_DEFAULT)


def goal_target(text: str) -> int | None:
    """The range the user asked for, in percentage points, if they named one (UW19)."""
    m = _TARGET.search(text)
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def history_days(text: str) -> int:
    lowered = text.lower()
    if m := _PAST_N.search(lowered):
        return int(m.group(1)) * _UNIT_DAYS[m.group(2)]
    if re.search(r"\b(this|last|past) week\b", lowered):
        return 7
    if re.search(r"\b(this|last|past) month\b", lowered):
        return 30
    if re.search(r"\b(since i started|ever|all time)\b", lowered):
        return 3650
    return 30


@dataclass(frozen=True)
class LifeEvent:
    label: str
    start: datetime
    end: datetime
    light: bool  # keep today's games light (UW9)

    def window(self, context_id: object, weight: float = 0.5) -> LifeContextWindow:
        return LifeContextWindow.model_validate(
            {
                "context_id": context_id,
                "label": self.label,
                "start": self.start,
                "end": self.end,
                "weight": weight,
            }
        )


_LABELS: list[tuple[re.Pattern[str], str, bool]] = [
    (re.compile(r"\b(slept|sleep|up all night|insomnia|no sleep)\b", re.I), "slept badly", True),
    (re.compile(r"\b(tired|exhausted|drained|wiped)\b", re.I), "tired", True),
    (re.compile(r"\b(ill|unwell|sick|headache|cold|flu|fever)\b", re.I), "feeling unwell", True),
    (re.compile(r"\bexams?\b|\brevision\b", re.I), "exam period", False),
    (re.compile(r"\b(jet ?lag|travell?ing|flew|flight)\b", re.I), "travelling", True),
    (
        re.compile(r"\b(stress\w*|busy|a lot going on|overwhelmed)\b", re.I),
        "busy or stressed",
        False,
    ),
]


def life_event(text: str, now: datetime, tz: ZoneInfo) -> LifeEvent | None:
    """What the user said about their life, as a labelled time window in their own day."""
    found = next(((label, light) for p, label, light in _LABELS if p.search(text)), None)
    if found is None:
        return None
    label, light = found
    lowered = text.lower()
    today = now.astimezone(tz).date()
    start = datetime.combine(today, time.min, tz)
    days = 1
    if re.search(r"\bnext week\b", lowered):
        start += timedelta(days=7 - today.weekday())  # next Monday, for the whole week
        days = 7
    elif re.search(r"\b(all|this|whole|busy) week\b|\bweek at\b", lowered):
        days = 7 - today.weekday()  # through Sunday
    elif re.search(r"\btomorrow\b", lowered) or label == "travelling":
        days = 2
    elif label == "exam period":
        days = 7 - today.weekday()
    if re.search(r"\b(until|till|through)\b", lowered) and (until := _weekday(lowered, today)):
        days = (until - today).days + 1
    end = start + timedelta(days=days)
    return LifeEvent(label, start.astimezone(UTC), end.astimezone(UTC), light)


PERSONA_WORDS: list[tuple[re.Pattern[str], Persona]] = [
    (re.compile(r"\bzitouna\b|\b(calm(er)?|gentle|patient|mentor)\b", re.I), "zitouna"),
    (re.compile(r"\bbarq\b|\b(energetic|hype|pump|trainer|punchy)\b", re.I), "barq"),
    (re.compile(r"\bhikma\b|\b(factual|analyst|numbers person|neutral)\b", re.I), "hikma"),
    (re.compile(r"\bsahbi\b|\b(friend|casual|funn(y|ier)|chill(er)? coach)\b", re.I), "sahbi"),
]
MODE_WORDS: list[tuple[re.Pattern[str], SuccessMode]] = [
    (re.compile(r"\bpush\b|\b(harder|challenge me more|tougher)\b", re.I), "push"),
    (re.compile(r"\bchill\b|\b(easier|relax\w*|lighter)\b", re.I), "chill"),
    (re.compile(r"\bbalanced\b|\bin between\b", re.I), "balanced"),
]


def persona_in(text: str) -> Persona | None:
    for pattern, persona in PERSONA_WORDS:
        if pattern.search(text):
            return persona
    return None


def mode_in(text: str) -> SuccessMode | None:
    if re.search(r"\bcoach\b", text, re.I) and persona_in(text):
        return None  # "a chill coach" is about the coach, not the games
    for pattern, mode in MODE_WORDS:
        if pattern.search(text):
            return mode
    return None


def asks_for_switches(text: str) -> bool:
    return bool(re.search(r"\b(camera|microphone|mic|voice|notifications?)\b", text, re.I))
