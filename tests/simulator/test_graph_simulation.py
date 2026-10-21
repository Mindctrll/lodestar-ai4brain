"""Simulator runs through the real graph. WP2.3 "Done when": Balanced success stays at 80 +/- 5%.
WP2.9 "Done when": frustration-prone users trigger easing."""

import numpy as np
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.registry.loader import load_registry
from simulator.graph_run import balanced_success, ease_rate, simulate_through_graph
from simulator.population import make_population
from tests.backend.agent.conftest import RunnerFactory


async def test_graph_keeps_balanced_success_near_80(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    registry = load_registry()
    runner = await make_runner()
    rng = np.random.default_rng(7)
    users = make_population(registry, 12, rng, kinds={"normal": 1.0})
    runs = await simulate_through_graph(runner, aengine, registry, users, 5, rng)
    success, n = balanced_success(runs)
    assert n >= 80
    assert abs(success - 0.8) <= 0.05, success
    first = runs[0].rounds[:6]
    assert [r.game_id for r in first] == registry.batteries["onboarding"].games


async def test_frustration_prone_users_trigger_easing(
    make_runner: RunnerFactory, aengine: AsyncEngine
) -> None:
    registry = load_registry()
    runner = await make_runner()
    rng = np.random.default_rng(11)
    users = make_population(registry, 6, rng, kinds={"normal": 1.0}) + make_population(
        registry, 6, rng, kinds={"frustration_prone": 1.0}
    )
    runs = await simulate_through_graph(runner, aengine, registry, users, 3, rng)
    prone, normal = ease_rate(runs, "frustration_prone"), ease_rate(runs, "normal")
    print(f"ease or break after a round: frustration-prone {prone:.2f}, normal {normal:.2f}")
    assert prone >= 0.25 and normal <= 0.1 and prone >= 3 * normal
