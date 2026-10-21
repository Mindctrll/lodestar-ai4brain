"""WP2.3 "Done when": a simulator run through the real graph keeps Balanced success at 80 +/- 5%."""

import numpy as np
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.registry.loader import load_registry
from simulator.graph_run import balanced_success, simulate_through_graph
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
