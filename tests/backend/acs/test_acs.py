from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.acs.events import from_trials, iteration
from backend.acs.score import WEIGHTS, effective_weights, score
from backend.acs.sensitivity import analyse
from backend.contracts.trial import TrialEvent

T0 = datetime(2026, 10, 21, tzinfo=UTC)


def test_new_user_has_no_score_yet() -> None:
    result = score({})
    assert result.value is None
    assert all(c.mean == 0.5 for c in result.components)  # Beta(2, 2) prior


def test_formula_matches_the_plan() -> None:
    counts = {"V": (8, 10), "A": (5, 10), "I": (5, 5), "C": (2, 4), "R": (3, 5)}
    result = score(counts)  # type: ignore[arg-type]
    # C has fewer than 5 opportunities: its weight is spread over the others.
    eff = effective_weights(counts)  # type: ignore[arg-type]
    assert eff["C"] == 0.0 and sum(eff.values()) == pytest.approx(1.0)
    assert eff["V"] == pytest.approx(0.30 / 0.85)
    s = {"V": 10 / 14, "A": 7 / 14, "I": 7 / 9, "R": 5 / 9}
    expected = 100 * sum(eff[k] * v for k, v in s.items())  # type: ignore[index]
    assert result.value == pytest.approx(expected)
    assert result.low is not None and result.high is not None
    assert result.low < result.value < result.high


def test_weights_sum_to_one() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def _trial(game: str, correct: bool, hints: int = 0) -> TrialEvent:
    return TrialEvent(
        trial_id=uuid4(), round_id=uuid4(), session_id=uuid4(), game_id=game, level=0.5,
        trial_index=0, stimulus={}, correct=correct, hint_level=hints, ts=T0,
    )  # fmt: skip


def test_observations_from_play() -> None:
    v = from_trials(
        "spot_the_mistake", [_trial("spot_the_mistake", True), _trial("spot_the_mistake", False)]
    )
    assert [(o.component, o.success) for o in v] == [("V", True), ("V", False)]
    a = from_trials("pattern_gap", [_trial("pattern_gap", True, 0), _trial("pattern_gap", True, 2)])
    assert [(o.component, o.success) for o in a] == [("A", True), ("A", False)]
    assert from_trials("echo", [_trial("echo", True)]) == []
    assert iteration("echo", 0.3, 0.6)[0].success and not iteration("echo", 0.3, 0.2)[0].success
    assert iteration("echo", 0.8, 0.9) == []  # not a retry after a failure


def test_experiment_7_rankings_are_stable_under_weight_changes() -> None:
    result = analyse(n=150, seed=3)
    assert result.worst_rho > 0.9, result.shifts
