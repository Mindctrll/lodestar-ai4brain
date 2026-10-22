"""WP3.3 units: engagement features and Venn-Abers ranges, the fatigue changepoint, the bandit."""

import numpy as np
import pytest

from backend.ml import bandit, fatigue
from backend.ml.engagement import (
    FEATURES,
    EngagementModel,
    feature_row,
    venn_abers,
    venn_abers_grid,
)

# Engagement ----------------------------------------------------------------------------------


def named(volume: list[float], fails: list[float] | None = None) -> dict[str, float]:
    v = np.array(volume, dtype=float)
    f = np.array(fails if fails is not None else [0.0] * len(volume))
    return dict(zip(FEATURES, feature_row(v, f, len(v) - 1), strict=True))


def test_features_read_the_days_the_same_way_for_oulad_and_lodestar() -> None:
    days = [0.0] * 20 + [5, 5, 0, 0, 2, 2, 2, 0, 0, 0, 1]  # last day is "today"
    row = named(days)
    assert row["days_since_last"] == 0 and row["streak"] == 1
    assert row["active_7"] == 4  # the last 7 days: 2, 2, 2, 0, 0, 0, 1
    assert row["active_prev_7"] == 2  # the 7 before: 0, 0, 0, 5, 5, 0, 0
    assert row["tenure"] == 10
    away = named([3.0] * 5 + [0.0] * 30)
    assert away["days_since_last"] == 30 and away["active_28"] == 0 and away["streak"] == 0
    capped = named([1.0] + [0.0] * 100)
    assert capped["days_since_last"] == 60  # capped, as in training


def test_activity_trend_is_a_ratio_so_clicks_and_rounds_compare() -> None:
    rounds = named([0.0] * 7 + [2.0] * 7 + [1.0] * 7)
    clicks = named([0.0] * 7 + [40.0] * 7 + [20.0] * 7)
    assert (
        rounds["volume_trend"]
        == pytest.approx(clicks["volume_trend"])
        == pytest.approx(np.log(0.5))
    )


def test_failures_count_over_the_last_28_days() -> None:
    row = named([1.0] * 40, fails=[1.0] * 5 + [0.0] * 30 + [1.0, 0, 1.0, 0, 0])
    assert row["fails_28"] == 2


def test_venn_abers_ranges_are_ordered_and_calibrated() -> None:
    rng = np.random.default_rng(0)
    scores = rng.normal(0, 2, 6000)
    labels = (rng.random(6000) < 1 / (1 + np.exp(-scores))).astype(float)
    grid, p0, p1 = venn_abers_grid(scores[:3000], labels[:3000], points=60)
    risks = [venn_abers(s, grid, p0, p1) for s in scores[3000:]]
    assert all(r.low <= r.p <= r.high for r in risks)
    p = np.array([r.p for r in risks])
    y = labels[3000:]
    for lo, hi in ((0.0, 0.3), (0.3, 0.7), (0.7, 1.0)):
        m = (p >= lo) & (p < hi)
        assert abs(y[m].mean() - p[m].mean()) < 0.05


def test_engagement_model_reads_from_its_stored_numbers() -> None:
    k = len(FEATURES)
    metrics = {
        "serving": {
            "mean": [0.0] * k,
            "scale": [1.0] * k,
            "coef": [1.0] + [0.0] * (k - 1),
            "intercept": -5.0,
            "grid": [-10.0, 0.0, 10.0],
            "p0": [0.0, 0.4, 0.9],
            "p1": [0.05, 0.5, 1.0],
        }
    }
    model = EngagementModel.from_metrics("v1", metrics)
    away = model.risk([30.0] + [0.0] * (k - 1))  # score 25: clipped at the top of the grid
    here = model.risk([0.0] * k)  # score -5
    assert away.high_risk and not here.high_risk
    assert here.low == pytest.approx(0.2) and here.high == pytest.approx(0.275)


# Fatigue -------------------------------------------------------------------------------------


def session(
    rng: np.random.Generator, change_at: float | None, minutes: float = 20.0, n: int = 80
) -> list[fatigue.Answer]:
    out = []
    for i in range(n):
        minute = minutes * i / n
        slow = change_at is not None and minute >= change_at
        rt = float(np.exp(rng.normal(np.log(600) + (0.6 if slow else 0.0), 0.25)))
        game = "echo" if i % 2 else "quick_draw"
        rt *= 3 if game == "echo" else 1  # mixed games: different usual speeds
        correct = bool(rng.random() < (0.7 if slow else 0.85))
        out.append(fatigue.Answer(minute, game, rt, correct))
    return out


def test_fatigue_point_finds_when_answers_slow_down() -> None:
    rng = np.random.default_rng(1)
    sessions = [session(rng, float(rng.uniform(9, 13))) for _ in range(8)]
    point = fatigue.fatigue_point(sessions)
    assert point is not None
    assert 9 <= point.median <= 13.5 and point.low <= point.median <= point.high
    assert point.sessions == 8


def test_no_fatigue_point_without_slowing_or_with_care() -> None:
    rng = np.random.default_rng(2)
    assert fatigue.fatigue_point([session(rng, None) for _ in range(8)]) is None
    assert fatigue.fatigue_point([session(rng, 10.0, n=20) for _ in range(8)]) is None  # too short
    careful = session(rng, 10.0)
    z = fatigue.standardise([careful])[0]
    minutes = np.array([a.minute for a in careful])
    assert fatigue.changepoint(z, minutes, [a.correct for a in careful]) is not None
    more_accurate = [False] * 40 + [True] * 40  # slower, but more right: care, not fatigue
    assert fatigue.changepoint(z, minutes, more_accurate) is None


def test_sessions_without_a_change_count_as_not_yet() -> None:
    rng = np.random.default_rng(3)
    early = [session(rng, 5.0) for _ in range(4)]
    point_early = fatigue.fatigue_point(early)
    with_long_calm = fatigue.fatigue_point(early + [session(rng, None) for _ in range(4)])
    assert point_early is not None and with_long_calm is not None
    assert with_long_calm.high >= point_early.high  # calm sessions push the curve later


# Bandit --------------------------------------------------------------------------------------


def test_each_change_is_credited_to_the_game_played_before_on_that_skill() -> None:
    rounds = [
        ("echo", "working_memory", 0.0),
        ("quick_draw", "processing_speed", 0.1),
        ("market_rush", "working_memory", 0.3),  # learned from echo
        ("echo", "working_memory", -0.1),  # learned from market_rush
    ]
    assert bandit.credited(rounds) == {"echo": [0.3], "market_rush": [-0.1]}


def test_population_prior_recovers_each_games_gain_per_round() -> None:
    rng = np.random.default_rng(4)
    true = {"echo": 0.05, "market_rush": 0.01}
    people = []
    for _ in range(400):
        rounds = []
        ability, est = 0.0, 0.0
        for _ in range(int(rng.integers(4, 12))):
            game = "echo" if rng.random() < 0.5 else "market_rush"
            new_est = ability + rng.normal(0, 0.3)
            rounds.append((game, "working_memory", new_est - est))
            est = new_est
            ability += true[game]
        people.append(rounds)
    priors = bandit.population_priors(people)
    assert priors["echo"].mean > priors["market_rush"].mean
    for game, gain in true.items():
        assert abs(priors[game].mean - gain) < 3 * priors[game].sd


def test_thompson_prefers_the_better_game_and_scales_skills() -> None:
    priors = {"echo": bandit.Prior(0.05, 0.01), "market_rush": bandit.Prior(0.0, 0.01)}
    posteriors = bandit.arms({}, ["echo", "market_rush", "quick_draw"], priors)
    assert posteriors["quick_draw"].sd == pytest.approx(bandit.UNKNOWN_SD)
    rng = np.random.default_rng(5)
    wins = sum(
        (s := bandit.thompson(posteriors, rng))["echo"] > s["market_rush"] for _ in range(200)
    )
    assert wins > 180
    gains = bandit.skill_gains(
        {"echo": 0.05, "market_rush": 0.0, "quick_draw": 0.01},
        {"working_memory": ["echo", "market_rush"], "processing_speed": ["quick_draw"]},
    )
    assert gains == {"working_memory": 1.0, "processing_speed": 0.0}
    assert not bandit.ready({"echo": [0.1] * 3}, {})
    assert bandit.ready({}, priors)
