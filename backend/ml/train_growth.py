"""Train and evaluate the growth forecast (docs/plan/10). Run with `make ml-train`.

Task: from a user's first n sessions with a game family (n = 3, 5, 8, 10), predict their score k
sessions later (k = 1, 3, 5, 10, 20), as an 80% range.

Models compared on held-out users (never the same user in two splits):
1. persistence (no change) and 2. a per-user power-law fit, each with split-conformal intervals;
3. LightGBM quantile regression (0.1, 0.5, 0.9) of the change from the last score, with
   conformalised quantile regression calibrated separately for each k, so each horizon gets its
   own coverage guarantee.

Writes the boosters to models/growth_forecast/<version>/, the model card, and (with --register)
an active row in agent.ml_models holding the metrics and the calibration.
"""

import argparse
import datetime as dt
import hashlib
import sys
import textwrap
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np

from backend.ml import conformal, curves, features

N_SET = (3, 5, 8, 10)
K_SET = (1, 3, 5, 10, 20)
QUANTILES = (0.1, 0.5, 0.9)
COVERAGE = 0.8
PER_CELL = {"train": 90_000, "calib": 30_000, "test": 30_000}
MODELS = Path("models/growth_forecast")
CARD = Path("backend/ml/model_cards/growth_forecast.md")
PARAMS: dict[str, Any] = {
    "objective": "quantile",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "verbose": -1,
    "num_threads": 0,
}
ROUNDS = 400


def split_of(user: np.ndarray) -> np.ndarray:
    """Users, not sessions: 60% train, 20% calibration, 20% test, fixed by a hash of the id."""
    h = np.array([int(hashlib.sha256(str(u).encode()).hexdigest()[:8], 16) % 10 for u in user])
    return np.where(h < 6, "train", np.where(h < 8, "calib", "test"))


def examples(
    c: curves.Curves, which: np.ndarray, n: int, k: int, cap: int, rng: np.random.Generator
) -> dict[str, np.ndarray]:
    ok = np.flatnonzero(which & (c.lengths() >= n + k))
    if len(ok) > cap:
        ok = rng.choice(ok, cap, replace=False)
    start = c.offsets[ok]
    idx = start[:, None] + np.arange(n)
    scores = c.score[idx]
    gaps = c.gap[idx]
    target = c.score[start + n + k - 1]
    ks = np.full(len(ok), k, dtype=np.float64)
    x = features.build(scores, gaps, ks, c.family[ok].astype(np.float64))
    return {
        "x": x,
        "y": target.astype(np.float64),
        "last": scores[:, -1].astype(np.float64),
        "k": ks,
    }


def stack(parts: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    return {key: np.concatenate([p[key] for p in parts]) for key in parts[0]}


def pinball(y: np.ndarray, pred: np.ndarray, q: float) -> float:
    d = y - pred
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def evaluate(
    name: str, y: np.ndarray, low: np.ndarray, mid: np.ndarray, high: np.ndarray
) -> dict[str, float]:
    return {
        "model": name,  # type: ignore[dict-item]
        "coverage": round(conformal.coverage(y, low, high), 4),
        "width": round(float(np.mean(high - low)), 4),
        "mae": round(float(np.mean(np.abs(y - mid))), 4),
        "pinball_mean": round(
            (pinball(y, low, 0.1) + pinball(y, mid, 0.5) + pinball(y, high, 0.9)) / 3, 4
        ),
    }


def train(seed: int = 2026) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    c = curves.curves()
    split = split_of(c.user)
    data = {
        s: stack([examples(c, split == s, n, k, PER_CELL[s], rng) for n in N_SET for k in K_SET])
        for s in ("train", "calib", "test")
    }
    family_col = features.FEATURES.index("family")
    boosters = {}
    train_set = lgb.Dataset(
        data["train"]["x"],
        data["train"]["y"] - data["train"]["last"],
        feature_name=features.FEATURES,
        categorical_feature=[family_col],
        free_raw_data=False,
    )
    for q in QUANTILES:
        boosters[q] = lgb.train({**PARAMS, "alpha": q, "seed": seed}, train_set, ROUNDS)

    def predict(d: dict[str, np.ndarray]) -> dict[float, np.ndarray]:
        out = {q: boosters[q].predict(d["x"]) + d["last"] for q in QUANTILES}
        lo, mid, hi = (np.sort(np.vstack([out[q] for q in QUANTILES]), axis=0)[i] for i in range(3))
        return {0.1: lo, 0.5: mid, 0.9: hi}

    cal, test = data["calib"], data["test"]
    pc, pt = predict(cal), predict(test)
    qhat = {
        int(k): conformal.calibrate_cqr(
            cal["y"][cal["k"] == k], pc[0.1][cal["k"] == k], pc[0.9][cal["k"] == k], COVERAGE
        )
        for k in K_SET
    }
    q_t = np.array([qhat[int(k)] for k in test["k"]])
    low, high = pt[0.1] - q_t, pt[0.9] + q_t

    # Baselines, each with its own split-conformal interval calibrated per k.
    gain_c = cal["x"][:, features.FEATURES.index("power_gain")]
    gain_t = test["x"][:, features.FEATURES.index("power_gain")]
    rows = []
    for name, mid_c, mid_t in (
        ("persistence", cal["last"], test["last"]),
        ("power law", cal["last"] + gain_c, test["last"] + gain_t),
        ("LightGBM median", pc[0.5], pt[0.5]),
    ):
        qm = {
            int(k): conformal.calibrate_median(
                cal["y"][cal["k"] == k], mid_c[cal["k"] == k], COVERAGE
            )
            for k in K_SET
        }
        w = np.array([qm[int(k)] for k in test["k"]])
        rows.append(evaluate(f"{name} + conformal", test["y"], mid_t - w, mid_t, mid_t + w))
    rows.append(evaluate("LightGBM quantiles, raw", test["y"], pt[0.1], pt[0.5], pt[0.9]))
    main = evaluate("LightGBM quantiles + CQR (used)", test["y"], low, pt[0.5], high)
    rows.append(main)
    by_k = {
        int(k): evaluate(
            f"k={int(k)}",
            test["y"][test["k"] == k],
            low[test["k"] == k],
            pt[0.5][test["k"] == k],
            high[test["k"] == k],
        )
        for k in K_SET
    }
    by_n = {
        int(n): evaluate(f"n={int(n)}", test["y"][m], low[m], pt[0.5][m], high[m])
        for n in N_SET
        for m in [test["x"][:, 0] == n]
    }
    version = dt.date.today().isoformat()
    folder = MODELS / version
    folder.mkdir(parents=True, exist_ok=True)
    for q, booster in boosters.items():
        booster.save_model(folder / f"q{int(q * 100):02d}.txt")
    return {
        "version": version,
        "folder": str(folder),
        "counts": {s: len(d["y"]) for s, d in data.items()},
        "users": {s: len(np.unique(c.user[split == s])) for s in ("train", "calib", "test")},
        "curves": len(c),
        "comparison": rows,
        "main": main,
        "by_k": by_k,
        "by_n": by_n,
        "qhat": qhat,
        "coverage_nominal": COVERAGE,
        "features": features.FEATURES,
    }


def card(result: dict[str, Any]) -> str:
    def table(rows: list[dict[str, Any]], first: str) -> str:
        head = (
            f"| {first} | Coverage (nominal 80%) | Mean width | MAE of median | Mean pinball |\n"
            "|---|---|---|---|---|\n"
        )
        return head + "\n".join(
            f"| {r['model']} | {r['coverage'] * 100:.1f}% | {r['width']:.3f} | {r['mae']:.3f} "
            f"| {r['pinball_mean']:.3f} |"
            for r in rows
        )

    main = result["main"]
    n = result["counts"]
    users = result["users"]
    data = textwrap.fill(
        f"{result['curves']:,} learning curves (one per person and game family) from 36,297 "
        "players. One point per session in which the family was played. Scores are put on a "
        "population scale (0 = the family's first-session mean, 1 = its spread), close to a "
        "Brain Twin estimate. The OSF project states no licence: the data is used for research "
        "and this competition only, kept out of the repository and never redistributed. No "
        "demographic field is used.",
        100,
    )
    split = textwrap.fill(
        f"Split by person, never by session: {users['train']:,} people for training, "
        f"{users['calib']:,} for calibration and {users['test']:,} for testing ({n['train']:,}, "
        f"{n['calib']:,} and {n['test']:,} examples). Training needs about 7 GB of memory and "
        "5 minutes on 8 cores.",
        100,
    )
    return f"""# Model card: Growth Forecast

Generated by `make ml-train` (backend/ml/train_growth.py) on {result["version"]}.
Do not edit by hand.

## What it does

From a person's first sessions with a kind of game, it predicts their score after k more sessions
(k = 1 to 20) as an **80% range**. Lodestar shows it on progress curves and in coaching, always with
the range (AGENTS.md rule 5).

## Data

Lumosity learning data (Steyvers & Schafer 2020, *Nature Human Behaviour*; https://osf.io/g9zkf/).
{data}

{split}

## Method

LightGBM quantile regression (0.1, 0.5, 0.9) of the change from the last score, with features from
the scores so far (level, slope, curvature, spread, a power-law fit) and the sessions between them,
plus the game family. The 0.1 and 0.9 predictions are then **conformalised** on the calibration
people, separately for each k (conformalised quantile regression), which guarantees about 80%
coverage for people like those in the data.

## Results on held-out people

Observed coverage of the 80% range: **{main["coverage"] * 100:.1f}%** (target 77-83%).

{table(result["comparison"], "Model")}

By sessions ahead (k):

{table(list(result["by_k"].values()), "Horizon")}

By sessions seen so far (n):

{table(list(result["by_n"].values()), "History")}

Width and MAE are in population standard deviations.

## Limits

- Lumosity players are mostly English-speaking adults who chose to train online; Lodestar's users,
  games and scoring differ. In the app, the input is the Brain Twin estimate per day of practice,
  not a raw game score, and each skill is mapped to its closest Lumosity game family
  (`forecast_family` in registry/dimensions.yaml). Coverage on Lodestar users must be re-checked
  once pilot data exists.
- No timestamps: "sessions" are sessions with that game family, not days.
- It forecasts practice scores, not health, intelligence or ability outside these games.

## Must not be used for

Judging a person, comparing people, or anything clinical. Never shown without its range.
"""


def register(result: dict[str, Any]) -> None:
    from sqlalchemy import create_engine, update

    from backend.db import tables as t
    from backend.db.engine import sync_url

    engine = create_engine(sync_url())
    with engine.begin() as conn:
        conn.execute(
            update(t.ml_models).where(t.ml_models.c.name == "growth_forecast").values(active=False)
        )
        conn.execute(
            t.ml_models.insert().values(
                name="growth_forecast",
                version=result["version"],
                metrics={k: v for k, v in result.items() if k not in ("folder",)},
                artefact_path=result["folder"],
                trained_at=dt.datetime.now(dt.UTC),
                active=True,
            )
        )
    engine.dispose()


def stored_result() -> dict[str, Any]:
    """The active model's training result, as registered (to rewrite the card without
    retraining)."""
    from sqlalchemy import create_engine, select

    from backend.db import tables as t
    from backend.db.engine import sync_url

    engine = create_engine(sync_url())
    with engine.connect() as conn:
        metrics: dict[str, Any] = conn.execute(
            select(t.ml_models.c.metrics).where(
                t.ml_models.c.name == "growth_forecast", t.ml_models.c.active.is_(True)
            )
        ).scalar_one()
    engine.dispose()
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", action="store_true", help="make it the active model")
    parser.add_argument("--card-only", action="store_true", help="rewrite the card from the DB")
    args = parser.parse_args(argv)
    if args.card_only:
        CARD.write_text(card(stored_result()), encoding="utf-8")
        return 0
    result = train()
    CARD.write_text(card(result), encoding="utf-8")
    main_cov = result["main"]["coverage"]
    print(f"held-out coverage {main_cov * 100:.1f}% (nominal 80%); card at {CARD}")
    if args.register:
        register(result)
    return 0 if 0.77 <= main_cov <= 0.83 else 1


if __name__ == "__main__":
    sys.exit(main())
