import random

from hypothesis import given
from hypothesis import strategies as st

from backend.scoring.hshs import hshs_score, hshs_success
from backend.scoring.kalman_elo import Belief, logistic
from backend.scoring.norms import Norms
from backend.scoring.quality import TrialSample, assess_quality
from backend.scoring.staircase import Staircase


@given(st.booleans(), st.floats(0, 5000), st.floats(100, 5000))
def test_hshs_stays_in_unit_interval(correct: bool, rt: float, deadline: float) -> None:
    assert 0.0 <= hshs_score(correct, rt, deadline) <= 1.0
    assert 0.0 <= hshs_success(correct, rt, deadline) <= 1.0


def test_hshs_rewards_fast_right_and_punishes_fast_wrong() -> None:
    assert hshs_score(True, 100, 1000) > hshs_score(True, 900, 1000) > 0.5
    assert hshs_score(False, 100, 1000) < hshs_score(False, 900, 1000) < 0.5
    assert hshs_score(True, 1000, 1000) == hshs_score(False, 1000, 1000) == 0.5


def test_hshs_success_scale() -> None:
    assert hshs_success(True, 400, 1000) == 1.0  # right, on pace
    assert hshs_success(False, 400, 1000) == 0.0  # wrong, on pace
    assert 0.5 < hshs_success(True, 800, 1000) < 1.0  # right but slow counts partly


def test_staircase_2_down_1_up_converges_near_71_percent() -> None:
    rng = random.Random(3)
    stair = Staircase(value=0.0, step=0.1, down=2, harder_is_lower=False)
    hits = total = 0
    for i in range(4000):
        correct = rng.random() < logistic(1.0 - stair.value)
        stair = stair.respond(correct)
        if i > 500:
            hits += correct
            total += 1
    assert abs(hits / total - 0.707) < 0.04


def test_percentile_range_brackets_the_value() -> None:
    pr = Norms().percentile("working_memory", Belief(mu=0.3, sigma=0.4))
    assert pr.low < pr.value < pr.high
    assert pr.source == "simulated"
    assert pr.label().startswith(f"{pr.value:.0f}% (likely")


def _honest(rng: random.Random, n: int = 30) -> list[TrialSample]:
    return [TrialSample(rng.random() < 0.8, rng.lognormvariate(6.3, 0.2)) for _ in range(n)]


def test_quality_flags_random_clickers_and_cheaters_but_not_honest_players() -> None:
    rng = random.Random(5)
    for _ in range(50):
        assert assess_quality(_honest(rng)).trust == 1.0
    random_clicker = [TrialSample(rng.random() < 0.5, rng.uniform(150, 350)) for _ in range(30)]
    assert assess_quality(random_clicker).verdict == "random_clicking"
    cheater = [TrialSample(True, rng.uniform(60, 140)) for _ in range(30)]
    assert assess_quality(cheater).verdict == "impossible_speed"
    assert assess_quality(_honest(rng, 4)).verdict == "too_few"
