import numpy as np

from backend.registry.loader import load_registry
from simulator.experiments import coverage, established_tracked, recovery, success_rate
from simulator.population import correlation_matrix, make_population
from simulator.run import simulate_user


def test_correlation_matrix_is_valid() -> None:
    dims = ["inhibition", "working_memory", "reasoning", "verbal_skill"]
    corr = correlation_matrix(dims)
    assert np.allclose(corr, corr.T)
    assert np.all(np.linalg.eigvalsh(corr) > 0)
    assert corr[0, 1] > corr[0, 2]  # executive functions correlate more


def test_small_simulation_runs_end_to_end() -> None:
    registry = load_registry()
    rng = np.random.default_rng(0)
    runs = [simulate_user(u, registry, 4, rng) for u in make_population(registry, 30, rng)]
    dims = established_tracked(registry, runs)
    assert len(dims) >= 8  # a short run may not reach every skill
    assert recovery(runs, dims, 3).mean_r > 0.5
    assert 0.5 < coverage(runs, dims, [3, 4]) <= 1.0
    assert 0.6 < success_rate(runs).overall < 0.95


def test_practice_follows_a_power_law() -> None:
    registry = load_registry()
    user = make_population(registry, 1, np.random.default_rng(1))[0]
    gains = []
    for _ in range(5):
        before = user.theta("working_memory")
        user.practise("working_memory", 1.0)
        gains.append(user.theta("working_memory") - before)
    assert gains == sorted(gains, reverse=True) and gains[0] > 0
