"""Best next game (docs/plan/10, section 4): Thompson sampling on each game's gain per round.

An arm is a (person, game) pair: the expected change in the Brain Twin estimate of the game's
main skill from one more round of it. The rewards come from the `twin.updated` events, so
nothing new is stored.

One round's change is mostly measurement noise (about 0.3 logits against a learning step of
0.02-0.05), and a round measures what the person could do when it started, so its change was
learned earlier. A person's own rounds alone can't tell games apart for months. So:

1. **Everyone's prior.** For each skill, a least-squares fit across people of how much the
   estimate moved after their first round of the skill, against how many rounds of each game
   came before their last one. Learning adds up over rounds while the noise doesn't, so this
   recovers each game's gain per round (with its standard error) far better than single
   changes do. On the simulator it needs a few hundred people.
2. **The person's own rounds** then move each arm's posterior away from that prior: each change
   is credited to the game played before it on the same skill.
3. **Thompson sampling.** One sample from every posterior; the best sample wins. Games we know
   little about get tried, games that help get favoured.

`plan_next` (docs/plan/03) gets `bandit_gain(skill)` from the best sample among the skill's
games, scaled to 0-1 across the skills on offer, and plays the game with the best sample.
"""

import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from backend.db import tables as t
from backend.registry.models import Registry

UNKNOWN_SD = 0.10  # a game without a population estimate: a wide prior around zero
PERSONAL_SD = 0.01  # how far one person's gain per round from a game strays from everyone's
NOISE_SD = 0.30  # the spread of one round's credited change (mostly measurement)
MIN_PATHS = 30  # people with 3+ rounds of a skill before that skill's games get a prior
MIN_ROUNDS = 10  # with no population prior yet, the person's own rounds before the bandit acts
RECENT_ROUNDS = 300
POPULATION_ROUNDS = 50_000
POPULATION_TTL_S = 600.0

Change = tuple[str, str, float]  # (game, its main skill, change of that skill's estimate)


@dataclass(frozen=True)
class Prior:
    mean: float
    sd: float


@dataclass(frozen=True)
class Arm:
    game_id: str
    rounds: int
    mean: float  # posterior mean gain per round
    sd: float


def credited(rounds: Iterable[Change]) -> dict[str, list[float]]:
    """One person's changes, oldest first: each goes to the game played before it on the same
    skill."""
    last: dict[str, str] = {}
    out: dict[str, list[float]] = {}
    for game_id, dim, change in rounds:
        if dim in last:
            out.setdefault(last[dim], []).append(change)
        last[dim] = game_id
    return out


def population_priors(people: Iterable[Sequence[Change]]) -> dict[str, Prior]:
    """Each game's gain per round across everyone, from the fit described above."""
    rows: dict[str, list[tuple[dict[str, int], float]]] = {}
    for rounds in people:
        paths: dict[str, list[tuple[str, float]]] = {}
        for game_id, dim, change in rounds:
            paths.setdefault(dim, []).append((game_id, change))
        for dim, path in paths.items():
            if len(path) < 3:
                continue
            counts: dict[str, int] = {}
            for game_id, _ in path[:-1]:  # the last round's learning isn't measured yet
                counts[game_id] = counts.get(game_id, 0) + 1
            rows.setdefault(dim, []).append((counts, sum(c for _, c in path[1:])))
    out: dict[str, Prior] = {}
    for data in rows.values():
        games = sorted({g for counts, _ in data for g in counts})
        if len(data) < max(MIN_PATHS, len(games) + 2):
            continue
        x = np.array([[counts.get(g, 0) for g in games] for counts, _ in data], dtype=float)
        y = np.array([total for _, total in data])
        coef, *_ = np.linalg.lstsq(x, y, rcond=None)
        resid = y - x @ coef
        cov = np.linalg.pinv(x.T @ x) * float(resid @ resid) / (len(y) - len(games))
        for i, game_id in enumerate(games):
            se = float(np.sqrt(max(cov[i, i], 0.0)))
            out[game_id] = Prior(float(coef[i]), float(np.hypot(PERSONAL_SD, se)))
    return out


def arm(game_id: str, gains: Sequence[float], prior: Prior | None) -> Arm:
    """Normal prior, normal noise: the conjugate update."""
    p = prior or Prior(0.0, UNKNOWN_SD)
    precision = 1.0 / p.sd**2 + len(gains) / NOISE_SD**2
    mean = (p.mean / p.sd**2 + sum(gains) / NOISE_SD**2) / precision
    return Arm(game_id, len(gains), mean, precision**-0.5)


def arms(
    gains: Mapping[str, Sequence[float]],
    games: Iterable[str],
    priors: Mapping[str, Prior] | None = None,
) -> dict[str, Arm]:
    return {g: arm(g, gains.get(g, []), (priors or {}).get(g)) for g in games}


def ready(gains: Mapping[str, Sequence[float]], priors: Mapping[str, Prior]) -> bool:
    """Worth using: everyone's data says something, or this person has played enough."""
    return bool(priors) or sum(len(v) for v in gains.values()) >= MIN_ROUNDS


def thompson(posteriors: Mapping[str, Arm], rng: np.random.Generator) -> dict[str, float]:
    return {g: float(rng.normal(a.mean, a.sd)) for g, a in sorted(posteriors.items())}


def skill_gains(
    samples: Mapping[str, float], games_by_skill: Mapping[str, Sequence[str]]
) -> dict[str, float]:
    """bandit_gain per skill: its best game's sample, scaled to 0-1 across the skills. No
    samples (no data yet): no gains."""
    best = {
        dim: max(samples[g] for g in games)
        for dim, games in games_by_skill.items()
        if games and all(g in samples for g in games)
    }
    if not best:
        return {}
    lo, hi = min(best.values()), max(best.values())
    if hi - lo < 1e-12:
        return dict.fromkeys(best, 0.0)
    return {dim: (v - lo) / (hi - lo) for dim, v in best.items()}


async def _changes(
    conn: AsyncConnection, registry: Registry, user_id: UUID | None, limit: int
) -> dict[UUID, list[Change]]:
    """Per person, oldest first: (game, main skill, change of its estimate) of recent rounds."""
    round_id = t.events.c.payload["round_id"].astext.cast(PgUUID(as_uuid=True))
    query = (
        select(t.events.c.user_id, t.events.c.ts, t.events.c.payload, t.rounds.c.game_id)
        .join(t.rounds, t.rounds.c.round_id == round_id)
        .where(t.events.c.type == "twin.updated")
        .order_by(t.events.c.ts.desc())
        .limit(limit)
    )
    if user_id is not None:
        query = query.where(t.events.c.user_id == user_id)
    out: dict[UUID, list[Change]] = {}
    for row in reversed((await conn.execute(query)).all()):
        try:
            primary = registry.game(row.game_id).primary_dims[0]
        except StopIteration, IndexError:  # a game no longer in the registry
            continue
        for change in row.payload.get("changes", []):
            if change["dim"] == primary:
                delta = change["mu_after"] - change["mu_before"]
                out.setdefault(row.user_id, []).append((row.game_id, primary, delta))
    return out


async def gains_by_game(
    conn: AsyncConnection, user_id: UUID, registry: Registry
) -> dict[str, list[float]]:
    """This person's credited gains per game."""
    rounds = await _changes(conn, registry, user_id, RECENT_ROUNDS)
    return credited(rounds.get(user_id, []))


_population: dict[int, tuple[float, dict[str, Prior]]] = {}


async def population(engine: AsyncEngine, registry: Registry) -> dict[str, Prior]:
    """Everyone's priors, from the latest rounds, recomputed every few minutes."""
    cached = _population.get(id(engine))
    if cached is not None and time.monotonic() - cached[0] < POPULATION_TTL_S:
        return cached[1]
    async with engine.connect() as conn:
        per_person = await _changes(conn, registry, None, POPULATION_ROUNDS)
    priors = population_priors(per_person.values())
    _population[id(engine)] = (time.monotonic(), priors)
    return priors
