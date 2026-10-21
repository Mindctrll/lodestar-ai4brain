"""WP3.3: on the simulator, where each person has hidden per-game learning rates, the bandit
beats random game choice (docs/plan/16)."""

from backend.registry.loader import load_registry
from simulator.bandit import compare


def test_bandit_beats_random_game_choice() -> None:
    c = compare(load_registry(), first_users=600, users=200, sessions=30)
    assert c.bandit_wins, c  # the 95% interval of the paired difference is above 0
    assert c.bandit_gain > c.random_gain and c.share_better > 0.5
