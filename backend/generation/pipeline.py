"""Content for one exercise (docs/plan/08):

    build (code) -> LLM rewords -> validate -> repair (max 2) -> else pool -> else code

Validators run in order: schema, content rules and solver, clinical-language filter, novelty
against what this user saw in the last 30 days. Play never waits on a failing LLM: the code-built
version is always valid, so it is the last resort.
"""

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.coach.language import find_banned
from backend.contracts.common import Contract
from backend.contracts.llm import LlmSelection
from backend.db import tables as t
from backend.generation.generators.base import Generator
from backend.generation.generators.registry import GENERATORS
from backend.llm.factory import LlmFactory, NoModelAvailable
from backend.memory.store import MemoryStore

log = logging.getLogger(__name__)

MAX_REPAIRS = 2
NOVELTY_DAYS = 30
NOVELTY_MAX = 0.9
PROMPTS = Path(__file__).parent / "prompts"
LEVELS: tuple[float, ...] = tuple(i / 10 for i in range(11))

Source = Literal["generated", "code", "pool"]


@dataclass
class Prepared:
    content: dict[str, Any]
    item_id: UUID
    source: Source
    report: dict[str, Any]
    degraded: list[str] = field(default_factory=list)


@cache
def load_prompt(name: str) -> tuple[str, str]:
    """(version, template) from prompts/<name>.md; the first line is `version: N`."""
    head, _, body = (PROMPTS / f"{name}.md").read_text(encoding="utf-8").partition("\n")
    return head.removeprefix("version:").strip(), body.strip()


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def level_bucket(level: float) -> float:
    return round(min(max(level, 0.0), 1.0), 1)


class ContentService:
    def __init__(
        self,
        engine: AsyncEngine,
        llm: LlmFactory | None,
        memory: MemoryStore | None = None,
        *,
        live_llm: Literal["when_needed", "always"] = "when_needed",
    ) -> None:
        """`live_llm`: play never waits on an LLM (docs/plan/08), so by default one is called
        during a session only when nothing else can serve the request (a theme with no curated
        list, UW4). Pool items are reworded in the background. Tests use "always"."""
        self.engine = engine
        self.llm = llm
        self.memory = memory
        self.live_llm = live_llm

    @staticmethod
    def needs_content(game_id: str) -> bool:
        return game_id in GENERATORS

    async def validate(
        self, gen: Generator, content: Contract, knobs: dict[str, float], user_id: UUID | None
    ) -> list[str]:
        try:
            content = gen.schema.model_validate(content.model_dump())
        except ValidationError as exc:
            return [f"schema: {e['loc']}: {e['msg']}" for e in exc.errors()]
        errors = gen.check(content, knobs)
        banned = {v.word for text in _strings(content.model_dump()) for v in find_banned(text)}
        errors += [f"banned word '{w}'" for w in sorted(banned)]
        if not errors and user_id is not None and self.memory is not None:
            try:
                since = datetime.now(UTC) - timedelta(days=NOVELTY_DAYS)
                similarity = await self.memory.max_similarity_served(
                    user_id, gen.game_id, gen.signature(content), since
                )
            except Exception:  # Qdrant down: skip the novelty check, the rest still holds
                log.warning("novelty check skipped for %s", gen.game_id)
            else:
                if similarity > NOVELTY_MAX:
                    errors.append(f"too similar to something served recently ({similarity:.2f})")
        return errors

    async def _llm_text(
        self,
        gen: Generator,
        content: Contract,
        knobs: dict[str, float],
        user_id: UUID,
        selection: LlmSelection,
        report: dict[str, Any],
    ) -> tuple[Contract | None, list[str]]:
        request = gen.text_request(content)
        if request is None or self.llm is None:
            return None, []
        version, template = load_prompt(request.prompt_name)
        report["prompt_version"] = version
        prompt = template.format(
            **{
                k: json.dumps(v) if not isinstance(v, str) else v
                for k, v in request.variables.items()
            }
        )
        messages: list[Any] = [
            SystemMessage("You write content for short practice games. Answer with JSON only."),
            HumanMessage(prompt),
        ]
        degraded: list[str] = []
        for attempt in range(1 + MAX_REPAIRS):
            try:
                reply = await self.llm.structured(user_id, selection, messages, request.schema)
            except NoModelAvailable as exc:
                return None, exc.degraded
            degraded = list(reply.degraded)
            report["model"] = f"{reply.provider}:{reply.model}"
            candidate = gen.apply_text(content, reply.value)
            errors = await self.validate(gen, candidate, knobs, user_id)
            report.setdefault("attempts", []).append(errors)
            if not errors:
                report["repairs"] = attempt
                return candidate, degraded
            messages.append(
                HumanMessage(
                    "That answer broke these rules:\n- "
                    + "\n- ".join(errors[:10])
                    + "\nFix them and answer again with JSON only."
                )
            )
        return None, degraded

    async def prepare(
        self,
        *,
        user_id: UUID,
        selection: LlmSelection,
        game_id: str,
        level: float,
        knobs: dict[str, float],
        seed: int,
        theme: str | None = None,
    ) -> Prepared | None:
        gen = GENERATORS.get(game_id)
        if gen is None:
            return None
        report: dict[str, Any] = {"validators": ["schema", "rules+solver", "language", "novelty"]}
        rng = random.Random(seed)
        content = gen.build(knobs, rng, theme)
        request = gen.text_request(content)
        needs_llm = request is not None and request.required
        improved: Contract | None = None
        degraded: list[str] = []
        if self.live_llm == "always" or needs_llm:
            improved, degraded = await self._llm_text(
                gen, content, knobs, user_id, selection, report
            )
        if improved is not None:
            return await self._serve(user_id, gen, improved, level, "generated", report, degraded)

        pooled = await self.take_from_pool(user_id, game_id, level, theme)
        if pooled is not None:
            pooled.degraded = degraded
            return pooled

        for retry in range(3):  # code-built content only fails on novelty: rebuild
            errors = await self.validate(gen, content, knobs, user_id)
            if not errors:
                break
            report.setdefault("code_retries", []).append(errors)
            content = gen.build(knobs, random.Random(seed + retry + 1), theme)
        return await self._serve(user_id, gen, content, level, "code", report, degraded)

    async def _serve(
        self,
        user_id: UUID,
        gen: Generator,
        content: Contract,
        level: float,
        source: Source,
        report: dict[str, Any],
        degraded: list[str],
    ) -> Prepared:
        data = content.model_dump(mode="json")
        async with self.engine.begin() as conn:
            item_id: UUID = (
                await conn.execute(
                    t.content_pool.insert()
                    .values(
                        game_id=gen.game_id,
                        level=level_bucket(level),
                        content=data,
                        validator_report={**report, "source": source},
                        prompt_version=report.get("prompt_version"),
                        model=report.get("model"),
                    )
                    .returning(t.content_pool.c.item_id)
                )
            ).scalar_one()
            await conn.execute(t.content_served.insert().values(user_id=user_id, item_id=item_id))
        await self._remember_served(user_id, gen, content, level, item_id)
        return Prepared(data, item_id, source, report, degraded)

    async def _remember_served(
        self, user_id: UUID, gen: Generator, content: Contract, level: float, item_id: UUID
    ) -> None:
        if self.memory is None:
            return
        try:
            await self.memory.record_served(
                user_id, gen.game_id, level, item_id, gen.signature(content)
            )
        except Exception:
            log.warning("could not record served content for novelty checks")

    async def take_from_pool(
        self, user_id: UUID, game_id: str, level: float, theme: str | None = None
    ) -> Prepared | None:
        """A pre-validated item near this level that this user hasn't seen."""
        gen = GENERATORS[game_id]
        served = select(t.content_served.c.item_id).where(t.content_served.c.user_id == user_id)
        query = (
            select(t.content_pool)
            .where(
                t.content_pool.c.game_id == game_id,
                func.abs(t.content_pool.c.level - level) <= 0.15,
                t.content_pool.c.item_id.not_in(served),
                t.content_pool.c.validator_report["pool"].as_boolean().is_(True),
            )
            .order_by(func.abs(t.content_pool.c.level - level))
            .limit(5)
        )
        async with self.engine.begin() as conn:
            rows = (await conn.execute(query)).all()
            row = next(
                (r for r in rows if theme is None or r.content.get("theme") in (None, theme)), None
            )
            if row is None:
                return None
            await conn.execute(
                t.content_served.insert().values(user_id=user_id, item_id=row.item_id)
            )
        content = gen.schema.model_validate(row.content)
        await self._remember_served(user_id, gen, content, level, row.item_id)
        return Prepared(row.content, row.item_id, "pool", row.validator_report)

    async def fill_pool(
        self,
        game_id: str,
        *,
        per_level: int = 30,
        levels: tuple[float, ...] = LEVELS,
        knobs_at: Any = None,
        seed: int = 0,
    ) -> int:
        """Top up the pool so every level bucket has `per_level` validated items (code-built;
        the operator's LLM can reword them later). Returns how many were added."""
        gen = GENERATORS[game_id]
        added = 0
        for level in levels:
            async with self.engine.connect() as conn:
                have = (
                    await conn.execute(
                        select(func.count())
                        .select_from(t.content_pool)
                        .where(
                            and_(
                                t.content_pool.c.game_id == game_id,
                                t.content_pool.c.level == level_bucket(level),
                                t.content_pool.c.validator_report["pool"].as_boolean().is_(True),
                            )
                        )
                    )
                ).scalar_one()
            knobs = knobs_at(level) if knobs_at else {}
            rows = []
            for i in range(max(0, per_level - have)):
                content = gen.build(
                    knobs, random.Random(f"{seed}:{game_id}:{level}:{have + i}"), None
                )
                errors = await self.validate(gen, content, knobs, None)
                if errors:
                    log.warning("pool item for %s failed validation: %s", game_id, errors[:3])
                    continue
                rows.append(
                    {
                        "game_id": game_id,
                        "level": level_bucket(level),
                        "content": content.model_dump(mode="json"),
                        "validator_report": {"pool": True, "source": "code"},
                    }
                )
            if rows:
                async with self.engine.begin() as conn:
                    await conn.execute(t.content_pool.insert(), rows)
                added += len(rows)
        return added
