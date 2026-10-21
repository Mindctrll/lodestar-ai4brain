"""WP2.7 growth forecast on synthetic learning curves (the real data is 2.6 GB and stays out of
CI; `make ml-train` reports the real numbers in the model card). Checks the power-law baseline,
the conformal quantile, that training yields calibrated 80% ranges on held-out people, and that
serving produces ordered bands."""

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.ml import conformal, curves, features, train_growth
from backend.ml.serve import GrowthForecaster, forecast_bands
from backend.registry.loader import load_registry

REGISTRY = load_registry()


def synthetic(people: int = 2400, sessions: int = 32, seed: int = 0) -> curves.Curves:
    """Power-law learners with their own start, gain and rate, plus session noise."""
    rng = np.random.default_rng(seed)
    families = np.array([6, 10])
    users, fams, offsets, scores, gaps = [], [], [0], [], []
    for u in range(people):
        for fam in families:
            length = int(rng.integers(12, sessions + 1))
            t = np.arange(1, length + 1)
            start = rng.normal(0, 1)
            gain = abs(rng.normal(1.2 if fam == 6 else 0.8, 0.4))
            rate = rng.uniform(0.3, 1.0)
            y = start + gain * (1 - t ** (-rate)) + rng.normal(0, 0.35, length)
            users.append(u)
            fams.append(fam)
            scores.append(y)
            g = np.r_[0, rng.integers(1, 3, length - 1)]
            gaps.append(g)
            offsets.append(offsets[-1] + length)
    return curves.Curves(
        user=np.array(users),
        family=np.array(fams),
        offsets=np.array(offsets),
        score=np.concatenate(scores).astype(np.float32),
        gap=np.concatenate(gaps).astype(np.float32),
        family_scale={6: (0.0, 1.0), 10: (0.0, 1.0)},
    )


def test_power_law_recovers_a_clean_curve() -> None:
    t = np.arange(1, 6, dtype=np.float64)
    y = 3.0 - 2.0 * t**-0.5
    gain, c = features.power_law(y[None, :], np.array([5.0]))
    truth = (3.0 - 2.0 * 10**-0.5) - y[-1]
    assert c[0] == 0.5 and gain[0] == pytest.approx(truth, abs=1e-6)


def test_conformal_quantile_covers_new_data() -> None:
    rng = np.random.default_rng(1)
    q = conformal.calibrate_median(rng.normal(0, 1, 2000), np.zeros(2000), 0.8)
    new = rng.normal(0, 1, 20000)
    assert conformal.coverage(new, -q * np.ones_like(new), q * np.ones_like(new)) == pytest.approx(
        0.8, abs=0.02
    )


@pytest.fixture(scope="module")
def trained(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    mp = pytest.MonkeyPatch()
    data = synthetic()
    mp.setattr(train_growth.curves, "curves", lambda: data)
    mp.setattr(train_growth, "PER_CELL", {"train": 4000, "calib": 2000, "test": 2000})
    mp.setattr(train_growth, "ROUNDS", 120)
    mp.setattr(train_growth, "N_SET", (3, 5, 8))
    mp.setattr(train_growth, "K_SET", (1, 5, 10))
    mp.setattr(train_growth, "MODELS", Path(tmp_path_factory.mktemp("models")))
    yield train_growth.train()
    mp.undo()


def test_training_gives_honest_80_percent_ranges(trained: dict[str, Any]) -> None:
    """The WP2.7 check: held-out coverage within 77-83% for nominal 80%, overall and per horizon."""
    assert 0.77 <= trained["main"]["coverage"] <= 0.83, trained["main"]
    for row in trained["by_k"].values():
        assert 0.74 <= row["coverage"] <= 0.86, row
    users = trained["users"]
    assert users["train"] and users["calib"] and users["test"]
    lgbm = trained["main"]
    persistence = next(r for r in trained["comparison"] if r["model"].startswith("persistence"))
    assert lgbm["mae"] < persistence["mae"]  # it learned something beyond "no change"
    card = train_growth.card(trained)
    assert "Observed coverage" in card and "Must not be used for" in card


def test_serving_gives_ordered_bands(trained: dict[str, Any]) -> None:
    model = GrowthForecaster.from_folder(trained["folder"], trained["qhat"], trained["version"])
    low, mid, high = model.predict([0.1, 0.4, 0.6, 0.7], [0, 1, 1, 1], 6, 5)
    assert low < mid < high and mid > 0.5  # a rising learner keeps rising, with a range
    today = date(2026, 10, 21)
    history = [(today - timedelta(days=d), "processing_speed", 0.1 * (5 - d)) for d in range(5)]
    history += [(today, "working_memory", 0.2)]  # one day only: no band
    bands = forecast_bands(model, REGISTRY, history, 5)
    assert set(bands) == {"processing_speed"}
    band = bands["processing_speed"]
    assert band.low <= band.median <= band.high and band.sessions_ahead == 5
    with pytest.raises(ValueError):
        model.predict([0.1, 0.2], [0, 1], 6, 5)


async def test_coach_facts_carry_the_forecast_with_its_range(
    trained: dict[str, Any], make_runner: Any, aengine: Any
) -> None:
    from dataclasses import replace

    from backend.db import tables as t
    from tests.backend.agent.test_graph import collect, interrupt_of, play
    from tests.backend.agent.test_policy import returning_user

    runner = await make_runner()
    model = GrowthForecaster.from_folder(trained["folder"], trained["qhat"], trained["version"])
    runner.services = replace(runner.services, forecaster=model)
    user_id = await returning_user(aengine)
    today = date.today()
    async with aengine.begin() as conn:
        await conn.execute(
            t.history.insert(),
            [
                {"user_id": user_id, "day": today - timedelta(days=d), "dim": "processing_speed",
                 "mu": 0.1 * (4 - d), "sigma": 0.5, "n": 10}
                for d in range(1, 5)
            ],
        )  # fmt: skip
    session_id = await runner.create_session(user_id, "ui")
    spec = interrupt_of(await collect(runner, user_id, session_id, message="play Quick Draw"))
    await play(runner, aengine, user_id, session_id, spec, [True] * 8)
    state = await runner.graph.aget_state(runner.config(session_id))
    texts = [f.text for f in state.values["facts"].facts]
    forecast = [x for x in texts if x.startswith("Forecast for Processing speed")]
    assert forecast and "after 5 more sessions" in forecast[0] and "80% range" in forecast[0]


async def test_forecast_endpoint_returns_percent_ranges(
    trained: dict[str, Any], aengine: Any
) -> None:
    import httpx

    from backend.agent.context import Services
    from backend.api.deps import engine_dep
    from backend.api.main import create_app
    from backend.db import tables as t
    from backend.llm.factory import LlmFactory
    from tests.backend.agent.conftest import test_settings

    model = GrowthForecaster.from_folder(trained["folder"], trained["qhat"], trained["version"])
    app = create_app(with_lifespan=False)
    llm = LlmFactory(REGISTRY, test_settings(), aengine)
    app.dependency_overrides[engine_dep] = lambda: aengine
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        app.state.services = Services(engine=aengine, registry=REGISTRY, llm=llm)
        created = (await client.post("/users", json={"age_confirmed": True})).json()
        headers = {"Authorization": f"Bearer {created['token']}"}
        assert (await client.get("/forecast", headers=headers)).json() == []  # no model yet
        app.state.services = Services(engine=aengine, registry=REGISTRY, llm=llm, forecaster=model)
        user_id = created["user_id"]
        today = date.today()
        async with aengine.begin() as conn:
            await conn.execute(
                t.history.insert(),
                [
                    {"user_id": user_id, "day": today - timedelta(days=d), "dim": "working_memory",
                     "mu": 0.1 * (4 - d), "sigma": 0.5, "n": 10}
                    for d in range(4)
                ],
            )  # fmt: skip
        bands = (await client.get("/forecast?sessions=5", headers=headers)).json()
    [band] = bands
    assert band["dim"] == "working_memory" and band["sessions_ahead"] == 5
    assert 0 <= band["low"] <= band["median"] <= band["high"] <= 100
    assert "36,000 players" in band["note"]
