"""End-of-session "sleep" (docs/plan/04, "Consolidation"):

1. write the journal entry (Markdown) and one episodic point,
2. merge near-duplicate memories (cosine > 0.92 within the user's points),
3. promote repeated self-statements and preferences to facts, with a confidence,
4. rewrite core.md from the top facts,
5. lower the importance of old memories and delete expired ones.

Spotting contradicted facts needs an LLM judgement; WP3.2 adds it (`superseded_by`).
"""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from backend.memory.notes import Notes
from backend.memory.store import MemoryStore

DUPLICATE_COSINE = 0.92
PROMOTE_KINDS = {"self_statement", "preference"}
PROMOTE_AT = 2  # mentioned at least twice
OLD_DAYS = 30.0
OLD_DECAY = 0.9
CORE_MIN_CONFIDENCE = 0.6
CORE_MAX_FACTS = 10


@dataclass
class ConsolidationReport:
    merged: int = 0
    promoted: int = 0
    decayed: int = 0
    expired: int = 0
    core_lines: int = 0


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / ((math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))) or 1.0)


async def merge_duplicates(memory: MemoryStore, user_id: UUID, collection: str) -> int:
    points = await memory.points(user_id, collection, with_vectors=True)  # type: ignore[arg-type]
    points.sort(key=lambda p: p.payload["created_at"], reverse=True)  # keep the newest wording
    kept: list[Any] = []
    removed: list[UUID] = []
    for point in points:
        twin = next(
            (k for k in kept if _cos(k.vector["dense"], point.vector["dense"]) > DUPLICATE_COSINE),
            None,
        )
        if twin is None:
            kept.append(point)
            continue
        p, k = point.payload, twin.payload
        k["importance"] = max(k.get("importance", 0.5), p.get("importance", 0.5))
        k["count"] = k.get("count", 1) + p.get("count", 1)
        k["source_event_ids"] = sorted(
            set(k.get("source_event_ids", [])) | set(p.get("source_event_ids", []))
        )
        if "confidence" in k:
            k["confidence"] = max(k.get("confidence", 0.5), p.get("confidence", 0.5))
        removed.append(UUID(str(point.id)))
    for k in kept:
        if k.payload.get("count", 1) > 1:
            fields = {
                f: k.payload[f]
                for f in ("importance", "count", "source_event_ids", "confidence")
                if f in k.payload
            }
            await memory.set_payload(user_id, collection, UUID(str(k.id)), fields)  # type: ignore[arg-type]
    await memory.delete_points(user_id, collection, removed)  # type: ignore[arg-type]
    return len(removed)


async def promote_facts(memory: MemoryStore, user_id: UUID) -> int:
    episodic = await memory.points(user_id, "episodic")
    promoted = 0
    for point in episodic:
        p = point.payload
        if (
            p.get("kind") not in PROMOTE_KINDS
            or p.get("count", 1) < PROMOTE_AT
            or p.get("promoted")
        ):
            continue
        confidence = min(0.9, 0.5 + 0.1 * p.get("count", 1))
        await memory.write(
            user_id,
            p["text"],
            collection="facts",
            kind=p["kind"],
            importance=p.get("importance", 0.5),
            source_event_ids=[UUID(e) for e in p.get("source_event_ids", [])],
            confidence=confidence,
        )
        await memory.set_payload(user_id, "episodic", UUID(str(point.id)), {"promoted": True})
        promoted += 1
    if promoted:
        await merge_duplicates(memory, user_id, "facts")
    return promoted


async def decay_and_expire(memory: MemoryStore, user_id: UUID, now: datetime) -> tuple[int, int]:
    decayed = 0
    expired: list[UUID] = []
    for point in await memory.points(user_id, "episodic"):
        p = point.payload
        if p.get("expires_at") and datetime.fromisoformat(p["expires_at"]) < now:
            expired.append(UUID(str(point.id)))
            continue
        age = (now - datetime.fromisoformat(p["created_at"])).total_seconds() / 86_400
        if age > OLD_DAYS and p.get("importance", 0.5) > 0.05:
            await memory.set_payload(
                user_id,
                "episodic",
                UUID(str(point.id)),
                {"importance": p["importance"] * OLD_DECAY},
            )
            decayed += 1
    await memory.delete_points(user_id, "episodic", expired)
    return decayed, len(expired)


async def rewrite_core(
    memory: MemoryStore, notes: Notes, user_id: UUID, header_lines: list[str]
) -> int:
    facts = [
        p.payload
        for p in await memory.points(user_id, "facts")
        if not p.payload.get("superseded_by")
        and p.payload.get("confidence", 0) >= CORE_MIN_CONFIDENCE
    ]
    facts.sort(key=lambda f: f.get("confidence", 0), reverse=True)
    lines = [
        *header_lines,
        *(f"{f['text']} ({f['confidence']:.0%} sure)" for f in facts[:CORE_MAX_FACTS]),
    ]
    notes.write_core(user_id, lines)
    return len(lines)


async def consolidate_user(
    memory: MemoryStore,
    notes: Notes,
    user_id: UUID,
    *,
    summary: str,
    header_lines: list[str],
    source_event_ids: list[UUID] | None = None,
    day: date | None = None,
    now: datetime | None = None,
) -> ConsolidationReport:
    now = now or datetime.now(UTC)
    notes.append_journal(user_id, day or now.date(), summary)
    await memory.write(
        user_id,
        summary,
        kind="session_summary",
        importance=0.4,
        source_event_ids=source_event_ids or [],
        created_at=now,
    )
    report = ConsolidationReport()
    report.merged = await merge_duplicates(memory, user_id, "episodic")
    report.promoted = await promote_facts(memory, user_id)
    report.decayed, report.expired = await decay_and_expire(memory, user_id, now)
    report.core_lines = await rewrite_core(memory, notes, user_id, header_lines)
    return report
