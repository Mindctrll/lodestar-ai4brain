"""What the profile as a whole says should change the plan (docs/plan/07, 13): a skill that has
stopped moving gets a new format, and a split profile gets two tracks at their own levels. The
agent's plan_next and the dashboard read the same answer from here."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from backend.contracts.views import (
    DimensionView,
    PatternsView,
    PlateauView,
    SplitTrackView,
    SplitView,
)
from backend.db import tables as t
from backend.db.twin_store import read_twin
from backend.registry.models import Game, Registry
from backend.scoring.kalman_elo import Belief
from backend.scoring.levels import TARGET_P, next_level
from backend.scoring.norms import Norms
from backend.scoring.patterns import (
    PLATEAU_MAX_PERCENT,
    HistoryPoint,
    PlateauSpan,
    find_plateau,
    find_split,
)

# What to try differently, by family of skills: a change of approach, not only of game.
STRATEGY = {
    "attention": "Say the target to yourself before each round, and look away for one slow breath "
    "between rounds.",
    "control": "Slow down for the first few answers, then let your speed build back up.",
    "memory": "Group the items into small chunks, or link them into a little picture.",
    "reasoning": "Say the rule out loud before you answer, and check it on the next item.",
    "language": "Work it out in words first, then commit to an answer.",
    "speed": "Aim for a steady rhythm instead of your fastest possible answer.",
}
ADVANCED_TARGET = TARGET_P["push"]
FOUNDATION_TARGET = TARGET_P["chill"]
MAX_PLATEAUS = 3


async def last_played(conn: AsyncConnection, user_id: UUID) -> dict[str, datetime]:
    rows = await conn.execute(
        select(t.rounds.c.game_id, func.max(t.rounds.c.started_at))
        .where(t.rounds.c.user_id == user_id)
        .group_by(t.rounds.c.game_id)
    )
    return {r[0]: r[1] for r in rows}


def freshest(options: Sequence[Game], played: Mapping[str, datetime]) -> Game | None:
    """The game played longest ago, a never-played one first."""
    never = datetime.min.replace(tzinfo=UTC)
    return min(options, key=lambda g: played.get(g.id, never), default=None)


def new_format(
    dim: str,
    registry: Registry,
    by_dim: Mapping[str, Sequence[Game]],
    played: Mapping[str, datetime],
) -> tuple[Game | None, bool]:
    """A different way to practise a stuck skill: the skill's own least-recent game, or, when it
    has only one, the least-recent game of its family. Returns the game and whether it's the
    same skill."""
    own = list(by_dim.get(dim, []))
    usual = max(own, key=lambda g: played.get(g.id, datetime.min.replace(tzinfo=UTC)), default=None)
    others = [g for g in own if usual is None or g.id != usual.id]
    if others:
        return freshest(others, played), True
    group = registry.dimension(dim).group
    nearby = {
        g.id: g
        for d, games in by_dim.items()
        if d != dim and registry.dimension(d).group == group
        for g in games
    }
    return freshest(list(nearby.values()), played), False


async def read_patterns(
    conn: AsyncConnection,
    user_id: UUID,
    registry: Registry,
    norms: Norms,
    by_dim: Mapping[str, Sequence[Game]],
    now: datetime | None = None,
) -> PatternsView:
    now = now or datetime.now(UTC)
    twin = await read_twin(conn, user_id, now=now, norms=norms)
    styles = {d.id for d in registry.dimensions if d.style}
    views = [v for v in twin.dims if v.n > 0 and v.dim not in styles and v.dim in by_dim]
    played = await last_played(conn, user_id)

    points: dict[str, list[HistoryPoint]] = {}
    for h in twin.history:
        points.setdefault(h.dim, []).append(HistoryPoint(h.day, h.mu, h.n))
    spans: list[tuple[DimensionView, PlateauSpan]] = []
    for v in views:
        span = find_plateau(points.get(v.dim, []), now.date())
        if span is not None and v.percent < PLATEAU_MAX_PERCENT:
            spans.append((v, span))
    spans.sort(key=lambda found: found[1].swing)  # the flattest first
    plateaus: list[PlateauView] = []
    for v, span in spans[:MAX_PLATEAUS]:
        game, same = new_format(v.dim, registry, by_dim, played)
        definition = registry.dimension(v.dim)
        plateaus.append(
            PlateauView(
                dim=v.dim,
                name=definition.name,
                started=span.start,
                days=span.days,
                answers=span.answers,
                percent=v.percent,
                low=v.percent_low,
                high=v.percent_high,
                game_id=game.id if game else None,
                game_name=game.name if game else None,
                same_skill=same,
                strategy=STRATEGY.get(definition.group, STRATEGY["reasoning"]),
            )
        )

    split = None
    found = find_split(views)
    if found is not None:

        def track(
            v: DimensionView, kind: Literal["advanced", "foundation"], target: float
        ) -> SplitTrackView:
            game = freshest(by_dim.get(v.dim, []), played)
            return SplitTrackView(
                dim=v.dim,
                name=registry.dimension(v.dim).name,
                track=kind,
                percent=v.percent,
                low=v.percent_low,
                high=v.percent_high,
                level=next_level(Belief(v.mu, v.sigma), target),
                target_p=target,
                game_id=game.id if game else None,
                game_name=game.name if game else None,
            )

        split = SplitView(
            gap=round(found.strong.percent - found.weak.percent, 1),
            advanced=track(found.strong, "advanced", ADVANCED_TARGET),
            foundation=track(found.weak, "foundation", FOUNDATION_TARGET),
        )
    return PatternsView(plateaus=plateaus, split=split)
