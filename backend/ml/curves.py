"""Learning curves from the Lumosity data (docs/plan/10, Growth Forecast).

One curve per (user, game family): the user's mean normalised score in each session in which they
played that family, in session order, with the number of sessions since the previous point. Scores
are put on a population scale: (score - mean of first sessions) / sd of all scores in the family,
so 0 is where people start and 1 is the family's spread (close to a Brain Twin estimate, whose
population starts at mean 0, sd 1). Some families score on a multiplying scale, so first-session
spreads can be tiny; the all-session spread keeps them comparable. Rare outliers are clipped.

The 2.6 GB file is read in chunks; the result is cached in `data/lumosity/curves.npz`.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

SOURCE = Path("data/lumosity/gamedata_preprocessed.csv")
CACHE = Path("data/lumosity/curves.npz")
MAX_POINTS = 60  # sessions kept per curve
CLIP = (-6.0, 8.0)


@dataclass(frozen=True)
class Curves:
    """Flat arrays; curve i is points offsets[i]:offsets[i + 1]."""

    user: np.ndarray  # per curve
    family: np.ndarray  # per curve
    offsets: np.ndarray  # len(curves) + 1
    score: np.ndarray  # per point, population scale
    gap: np.ndarray  # per point, sessions since the previous point (0 for the first)
    family_scale: dict[int, tuple[float, float]]  # family -> (first-session mean, overall sd)

    def __len__(self) -> int:
        return len(self.user)

    def lengths(self) -> np.ndarray:
        return np.diff(self.offsets)


def build(source: Path = SOURCE, chunksize: int = 2_000_000) -> Curves:
    parts = []
    cols = ["anon_id", "master_game_id", "session", "score_norm"]
    for chunk in pd.read_csv(source, usecols=cols, chunksize=chunksize):
        chunk = chunk.dropna()
        g = chunk.groupby(["anon_id", "master_game_id", "session"])["score_norm"]
        parts.append(pd.DataFrame({"s": g.sum(), "n": g.count()}))
    agg = pd.concat(parts).groupby(level=[0, 1, 2]).sum()
    points = (agg["s"] / agg["n"]).rename("score").reset_index()
    points = points.sort_values(["anon_id", "master_game_id", "session"], kind="stable")
    points["rank"] = points.groupby(["anon_id", "master_game_id"]).cumcount()
    points = points[points["rank"] < MAX_POINTS]
    first = points[points["rank"] == 0].groupby("master_game_id")["score"].mean()
    spread = points.groupby("master_game_id")["score"].std()
    scale = {int(f): (float(first[f]), float(spread[f]) or 1.0) for f in first.index}
    mean = points["master_game_id"].map({f: m for f, (m, _) in scale.items()})
    sd = points["master_game_id"].map({f: s for f, (_, s) in scale.items()})
    points["z"] = ((points["score"] - mean) / sd).clip(*CLIP)
    points["gap"] = points.groupby(["anon_id", "master_game_id"])["session"].diff().fillna(0)
    keys = points[["anon_id", "master_game_id"]].to_numpy()
    starts = np.flatnonzero(np.r_[True, (keys[1:] != keys[:-1]).any(axis=1)])
    offsets = np.r_[starts, len(points)]
    return Curves(
        user=keys[starts, 0].astype(np.int64),
        family=keys[starts, 1].astype(np.int64),
        offsets=offsets.astype(np.int64),
        score=points["z"].to_numpy(np.float32),
        gap=points["gap"].to_numpy(np.float32),
        family_scale=scale,
    )


def save(curves: Curves, path: Path = CACHE) -> None:
    fams = np.array(sorted(curves.family_scale), dtype=np.int64)
    np.savez_compressed(
        path,
        user=curves.user,
        family=curves.family,
        offsets=curves.offsets,
        score=curves.score,
        gap=curves.gap,
        scale_family=fams,
        scale=np.array([curves.family_scale[int(f)] for f in fams], dtype=np.float64),
    )


def load(path: Path = CACHE) -> Curves:
    z = np.load(path)
    scale = {
        int(f): (float(m), float(s))
        for f, (m, s) in zip(z["scale_family"], z["scale"], strict=True)
    }
    return Curves(z["user"], z["family"], z["offsets"], z["score"], z["gap"], scale)


def curves(source: Path = SOURCE, cache: Path = CACHE) -> Curves:
    if cache.exists():
        return load(cache)
    built = build(source)
    save(built, cache)
    return built
