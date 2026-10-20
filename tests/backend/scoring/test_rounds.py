from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.contracts.trial import TrialEvent
from backend.registry.loader import load_registry
from backend.registry.models import Registry
from backend.scoring.kalman_elo import Belief
from backend.scoring.loadings import loading_matrix, update_weight
from backend.scoring.rounds import observed_score, score_round

T0 = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load_registry()


def _trials(
    game_id: str, results: list[bool], rt: float = 600.0, practice: int = 0
) -> list[TrialEvent]:
    round_id, session_id = uuid4(), uuid4()
    return [
        TrialEvent(
            trial_id=uuid4(), round_id=round_id, session_id=session_id, game_id=game_id,
            level=0.4, trial_index=i, practice=i < practice, stimulus={}, correct=c,
            rt_ms=rt, ts=T0 + timedelta(seconds=5 * i),
        )
        for i, c in enumerate(results)
    ]  # fmt: skip


def _beliefs(registry: Registry, game_id: str) -> dict[str, Belief]:
    return {d: Belief() for d in loading_matrix(registry)[game_id]}


def test_loading_matrix_skips_style_and_calibration(registry: Registry) -> None:
    matrix = loading_matrix(registry)
    assert "balloon_pump" not in matrix and "how_sure" not in matrix
    assert matrix["souk_rush"] == {"working_memory": 1.0, "short_term_memory": 0.5}


def test_good_round_raises_mu_and_lowers_sigma(registry: Registry) -> None:
    game = registry.game("echo")
    out = score_round(game, _trials("echo", [True] * 10 + [False] * 2), _beliefs(registry, "echo"),
                      loading_matrix(registry)["echo"])  # fmt: skip
    wm = out.beliefs["working_memory"]
    assert wm.mu > 0 and wm.sigma < 1.5 and wm.n == 12
    assert wm.last_practised == T0 + timedelta(seconds=55)


def test_practice_trials_do_not_count(registry: Registry) -> None:
    game = registry.game("echo")
    trials = _trials("echo", [True] * 3 + [False] * 10, practice=3)
    out = score_round(game, trials, _beliefs(registry, "echo"), loading_matrix(registry)["echo"])
    assert out.observations == 10 and out.beliefs["working_memory"].mu < 0


def test_secondary_loading_moves_less(registry: Registry) -> None:
    game = registry.game("souk_rush")
    out = score_round(game, _trials("souk_rush", [True] * 12), _beliefs(registry, "souk_rush"),
                      loading_matrix(registry)["souk_rush"])  # fmt: skip
    assert out.beliefs["working_memory"].mu > out.beliefs["short_term_memory"].mu > 0


def test_untrusted_round_changes_nothing(registry: Registry) -> None:
    game = registry.game("echo")
    beliefs = _beliefs(registry, "echo")
    cheat = _trials("echo", [True] * 12, rt=90.0)
    out = score_round(game, cheat, beliefs, loading_matrix(registry)["echo"])
    assert out.quality.verdict == "impossible_speed"
    assert out.beliefs == beliefs and out.observations == 0


def test_life_context_halves_the_update(registry: Registry) -> None:
    """UW9: rounds inside a flagged window move mu about half as much."""
    game = registry.game("echo")
    trials = _trials("echo", [True] * 9 + [False])
    loads = loading_matrix(registry)["echo"]
    start = {"working_memory": Belief(mu=0.0, sigma=0.6)}
    full = score_round(game, trials, start, loads).beliefs["working_memory"].mu
    half = score_round(game, trials, start, loads, context_weight=0.5).beliefs["working_memory"].mu
    assert 0.4 < half / full < 0.65


def test_hshs_game_uses_deadline_from_knobs(registry: Registry) -> None:
    game = registry.game("arrow_storm")
    fast, slow = (
        _trials("arrow_storm", [True], rt=300)[0],
        _trials("arrow_storm", [True], rt=1500)[0],
    )
    assert observed_score(game, fast) == 1.0
    assert observed_score(game, slow) is not None and observed_score(game, slow) < 1.0  # type: ignore[operator]


def test_anticipations_are_dropped(registry: Registry) -> None:
    game = registry.game("quick_draw")
    trial = _trials("quick_draw", [True], rt=100)[0]
    assert observed_score(game, trial) is None


def test_weights_validate_inputs() -> None:
    assert update_weight(1.0, 0.8, 0.5, 1.0) == pytest.approx(0.4)
    with pytest.raises(ValueError):
        update_weight(1.2, 1, 1, 1)
