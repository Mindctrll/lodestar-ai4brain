"""Plateaus, split profiles, and the mashing check (the jury's stress cases)."""

from dataclasses import dataclass
from datetime import date, timedelta

from backend.coach.verify import verify
from backend.contracts.facts import Fact, FactsPacket
from backend.scoring.kalman_elo import SIGMA_START, Belief, widen
from backend.scoring.patterns import HistoryPoint, find_plateau, find_split
from backend.scoring.quality import TrialSample, assess_quality

TODAY = date(2026, 11, 6)


def days(mus: list[float], gap: int = 3, per_day: int = 20) -> list[HistoryPoint]:
    n = len(mus)
    return [
        HistoryPoint(TODAY - timedelta(days=gap * (n - 1 - i)), mu, 100 + per_day * i)
        for i, mu in enumerate(mus)
    ]


def test_a_flat_stretch_of_practice_is_a_plateau() -> None:
    span = find_plateau(days([0.5, 0.52, 0.48, 0.5, 0.51, 0.49, 0.5]), TODAY)
    assert span is not None and span.days == 18 and span.answers == 120


def test_a_rising_skill_or_an_unpractised_one_is_not() -> None:
    assert find_plateau(days([0.1 * i for i in range(7)]), TODAY) is None
    assert find_plateau(days([0.5] * 7, per_day=0), TODAY) is None  # flat, but nobody played it
    assert find_plateau(days([0.5, 0.5]), TODAY) is None  # too short


@dataclass(frozen=True)
class View:
    percent: float
    percent_low: float
    percent_high: float
    sigma: float = 0.4


def test_a_split_needs_both_far_ends_and_ranges_that_do_not_touch() -> None:
    strong, weak = View(92, 86, 96), View(14, 8, 24)
    found = find_split([View(50, 40, 60), strong, weak])
    assert found is not None and found.strong is strong and found.weak is weak
    assert find_split([View(85, 78, 90), View(14, 8, 24)]) is None  # not at the far ends
    assert find_split([View(91, 30, 95), View(19, 5, 60)]) is None  # ranges overlap
    assert find_split([View(92, 86, 96, 1.2), View(14, 8, 24, 1.2)]) is None  # still measuring


def test_mashing_is_flagged_even_in_a_short_round() -> None:
    mashed = [TrialSample(i % 3 == 0, 90.0 + i) for i in range(6)]
    report = assess_quality(mashed)
    assert report.verdict == "random_clicking" and report.trust == 0.0
    assert report.median_rt_ms is not None and report.median_rt_ms < 100


def test_a_fast_careful_player_is_not_flagged() -> None:
    assert assess_quality([TrialSample(True, 380.0) for _ in range(10)]).verdict == "ok"


def test_widening_keeps_the_estimate_and_is_capped() -> None:
    wider = widen(Belief(0.7, 0.5), 1.35)
    assert wider.mu == 0.7 and wider.sigma > 0.5
    assert widen(Belief(0.7, 1.4), 1.35).sigma == SIGMA_START


def test_the_verifier_stops_promises_about_the_future() -> None:
    packet = FactsPacket(facts=[Fact(id="F1", text="Forecast: 66% (80% range 58-74%)")])
    assert not verify("You will definitely improve.", packet).ok
    assert not verify("Your score will be 66% [F1].", packet).ok
    assert verify("I can't say exactly: likely 58-74% [F1].", packet).ok
