import math
import random
from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from backend.scoring.kalman_elo import (
    SIGMA_START,
    Belief,
    add_process_noise,
    drift,
    interval,
    logistic,
    predict,
    update,
    update_item_difficulty,
)
from backend.scoring.levels import TARGET_P, next_level, target_b

mus = st.floats(-4, 4)
sigmas = st.floats(0.05, SIGMA_START)
bs = st.floats(-4, 4)
scores = st.floats(0, 1)
weights = st.floats(0, 1)


@given(mus, sigmas, bs, scores, weights)
def test_sigma_never_grows_from_an_answer(
    mu: float, sigma: float, b: float, s: float, w: float
) -> None:
    before = Belief(mu=mu, sigma=sigma)
    assert update(before, b, s, w).sigma <= before.sigma + 1e-12


@given(mus, sigmas, bs, scores, st.floats(0.01, 1))
def test_mu_moves_toward_the_evidence(
    mu: float, sigma: float, b: float, s: float, w: float
) -> None:
    before = Belief(mu=mu, sigma=sigma)
    after = update(before, b, s, w)
    p = predict(before, b)
    if s > p:
        assert after.mu >= before.mu
    elif s < p:
        assert after.mu <= before.mu


@given(mus, sigmas, st.floats(0, 400))
def test_drift_grows_sigma_but_stays_capped(mu: float, sigma: float, days: float) -> None:
    now = datetime(2026, 11, 1, tzinfo=UTC)
    before = Belief(mu=mu, sigma=sigma, last_practised=now - timedelta(days=days))
    after = drift(before, now)
    assert before.sigma - 1e-12 <= after.sigma <= SIGMA_START + 1e-12
    assert after.mu == before.mu


def test_three_weeks_away_blurs_noticeably() -> None:
    now = datetime(2026, 11, 1, tzinfo=UTC)
    before = Belief(sigma=0.3, last_practised=now - timedelta(days=21))
    assert drift(before, now).sigma > 0.35


@given(mus, sigmas)
def test_process_noise_is_capped(mu: float, sigma: float) -> None:
    after = add_process_noise(Belief(mu=mu, sigma=sigma))
    assert sigma - 1e-12 <= after.sigma <= SIGMA_START + 1e-12


def test_zero_weight_changes_nothing() -> None:
    belief = Belief(mu=0.3, sigma=0.9, n=4)
    assert update(belief, 0.0, 1.0, 0.0) == belief


@given(mus, sigmas, st.sampled_from(list(TARGET_P.values())))
def test_target_b_hits_target_exactly(mu: float, sigma: float, p_star: float) -> None:
    belief = Belief(mu=mu, sigma=sigma)
    assert math.isclose(predict(belief, target_b(belief, p_star)), p_star, abs_tol=1e-9)


def test_targeting_hits_p_star_on_synthetic_users() -> None:
    """Done-when for WP1.1: achieved success within p* +/- 0.05."""
    rng = random.Random(1)
    for p_star in (0.65, 0.80, 0.90):
        successes = trials = 0
        for _ in range(200):
            theta = rng.gauss(0, 1)
            belief = Belief()
            for i in range(80):
                b = target_b(belief, p_star)
                correct = rng.random() < logistic(theta - b)
                belief = update(belief, b, 1.0 if correct else 0.0, 1.0)
                if i >= 20:  # after the first few answers
                    successes += correct
                    trials += 1
        assert abs(successes / trials - p_star) < 0.05, p_star


def test_next_level_is_monotonic_in_skill() -> None:
    levels = [next_level(Belief(mu=mu, sigma=0.5), 0.8) for mu in (-2, -1, 0, 1, 2)]
    assert levels == sorted(levels)


def test_item_difficulty_learns_only_from_well_known_users() -> None:
    assert update_item_difficulty(0.5, 1.0, 0.6, learner_sigma=0.9) == 0.5
    assert update_item_difficulty(0.5, 1.0, 0.6, learner_sigma=0.4) < 0.5


def test_interval_is_80_percent() -> None:
    lo, hi = interval(Belief(mu=0.0, sigma=1.0))
    assert math.isclose(hi, 1.2816, abs_tol=1e-4) and math.isclose(lo, -hi)
