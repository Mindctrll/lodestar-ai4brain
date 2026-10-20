import pytest

from backend.coach.language import find_banned


@pytest.mark.parametrize(
    "text",
    [
        "This shows a memory deficit.",
        "No diagnosis here.",
        "Do I have ADHD?",
        "Your IQ went up.",
        "Your brain age is 25.",
        "That is abnormal.",
        "A normal result.",
        "Your brain is fast.",
    ],
)
def test_banned_words_are_caught(text: str) -> None:
    assert find_banned(text)


@pytest.mark.parametrize(
    "text",
    [
        "Your working memory is a growth area.",
        "This is within the typical range.",
        "Your results show steady practice.",
        "We normalize the scores.",
        "Add a goal for this week.",
    ],
)
def test_clean_text_passes(text: str) -> None:
    assert find_banned(text) == []


def test_allow_pragma_skips_line() -> None:
    assert find_banned("diagnosis  // lint-language: allow") == []


def test_reports_position_and_replacement() -> None:
    [violation] = find_banned("ok\nthe symptoms")
    assert (violation.line, violation.column) == (2, 5)
    assert violation.replacement == "pattern"
