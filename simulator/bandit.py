"""The best-next-game bandit against random game choice (docs/plan/10, section 4; WP3.3).

Each simulated person learns more from some games than from others: a hidden rate per game,
the product of an everyone-level rate (some games teach more in general) and a personal one,
both log-normal around 1. A first group of people plays with random games; their rounds give the
population prior, as everyone's events do in the app. A second group then plays twice from the
same start, with the same seeds: with random games, and with the bandit
(`backend.ml.bandit`: population prior, credited Brain Twin gains, Thompson sampling). Both pick
the skill the same way (the one the Brain Twin is least sure about); only the game differs.

    uv run python -m simulator.bandit --first 600 --users 200 --sessions 30
"""

import argparse
import copy
import sys
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from backend.ml import bandit
from backend.registry.loader import load_registry
from backend.registry.models import Game, Registry
from simulator.population import SimUser, make_population
from simulator.run import UserRun, random_game, simulate_user

POPULATION_SD = 0.4  # spread of the everyone-level rates (log scale)
PERSONAL_SD = 0.3  # spread of one person's rates around them


def changes(run: UserRun, registry: Registry) -> list[tuple[str, str, float]]:
    return [(r.game_id, registry.game(r.game_id).primary_dims[0], r.gain) for r in run.rounds]


def bandit_chooser(registry: Registry, priors: Mapping[str, bandit.Prior]):  # type: ignore[no-untyped-def]
    def choose(options: list[Game], run: UserRun, rng: np.random.Generator) -> Game:
        gains = bandit.credited(changes(run, registry))
        if not bandit.ready(gains, priors):
            return random_game(options, run, rng)
        samples = bandit.thompson(bandit.arms(gains, [g.id for g in options], priors), rng)
        return max(options, key=lambda g: samples[g.id])

    return choose


@dataclass(frozen=True)
class Comparison:
    users: int
    sessions: int
    random_gain: float  # mean true skill gained per person (sum over skills), random games
    bandit_gain: float
    diff_low: float  # 95% interval of the paired difference
    diff_high: float
    share_better: float  # people who gained more with the bandit

    @property
    def bandit_wins(self) -> bool:
        return self.diff_low > 0


def learned(run: UserRun) -> float:
    return float(sum(run.user.learned.values()))


def with_rates(
    people: list[SimUser], everyone: Mapping[str, float], rng: np.random.Generator
) -> list[SimUser]:
    for person in people:
        person.game_gain = {
            g: rate * float(np.exp(rng.normal(0.0, PERSONAL_SD))) for g, rate in everyone.items()
        }
    return people


def compare(
    registry: Registry, first_users: int, users: int, sessions: int, seed: int = 2026
) -> Comparison:
    rng = np.random.default_rng(seed)
    game_ids = [g.id for g in registry.games if g.kind == "game"]
    everyone = {g: float(np.exp(rng.normal(0.0, POPULATION_SD))) for g in game_ids}
    first = with_rates(make_population(registry, first_users, rng), everyone, rng)
    played = [
        changes(
            simulate_user(p, registry, sessions, np.random.default_rng([seed, 0, p.user_id])),
            registry,
        )
        for p in first
    ]
    priors = bandit.population_priors(played)
    choose = bandit_chooser(registry, priors)

    diffs, base, best = [], [], []
    for person in with_rates(make_population(registry, users, rng), everyone, rng):
        a = simulate_user(
            copy.deepcopy(person), registry, sessions, np.random.default_rng([seed, person.user_id])
        )
        b = simulate_user(
            copy.deepcopy(person),
            registry,
            sessions,
            np.random.default_rng([seed, person.user_id]),
            choose_game=choose,
        )
        base.append(learned(a))
        best.append(learned(b))
        diffs.append(best[-1] - base[-1])
    d = np.array(diffs)
    half = 1.96 * d.std(ddof=1) / np.sqrt(len(d))
    return Comparison(
        users=users,
        sessions=sessions,
        random_gain=float(np.mean(base)),
        bandit_gain=float(np.mean(best)),
        diff_low=float(d.mean() - half),
        diff_high=float(d.mean() + half),
        share_better=float((d > 0).mean()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=int, default=600, help="people behind the prior")
    parser.add_argument("--users", type=int, default=200, help="people in the comparison")
    parser.add_argument("--sessions", type=int, default=30)
    args = parser.parse_args(argv)
    c = compare(load_registry(), args.first, args.users, args.sessions)
    print(
        f"{c.users} people, {c.sessions} sessions: true gain {c.random_gain:.3f} with random "
        f"games, {c.bandit_gain:.3f} with the bandit (difference {c.diff_low:+.3f} to "
        f"{c.diff_high:+.3f}, 95%); {c.share_better * 100:.0f}% gained more with the bandit"
    )
    return 0 if c.bandit_wins else 1


if __name__ == "__main__":
    sys.exit(main())
