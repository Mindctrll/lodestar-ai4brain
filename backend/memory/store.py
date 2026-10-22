"""Searchable memory in Qdrant (docs/plan/04, "Qdrant"; AGENTS.md rule 7).

Every query on user data filters by `user_id`, and every public method that touches user data
takes the user id as a required argument, so a search without one can't be written. The shared
`knowledge` collection has its own read-only helper and holds no user data.

Retrieval recipe: one `query_points` call per collection (dense top 30 + sparse top 30, both
filtered by user, fused with RRF), then fused rank x relevance gate x importance x time decay,
then MMR so the top results aren't five versions of the same memory.
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from qdrant_client import AsyncQdrantClient, models

from backend.contracts.memory import MemoryHit
from backend.memory.embeddings import DENSE_SIZE, Embedder

UserCollection = Literal["episodic", "facts", "exercises"]
USER_COLLECTIONS: tuple[UserCollection, ...] = ("episodic", "facts", "exercises")
KNOWLEDGE = "knowledge"

PREFETCH = 30
DECAY_DAYS = 30.0
DECAY_FLOOR = 0.25  # an old but relevant memory still counts a quarter
# Fusion ranks carry no absolute relevance (dense search returns every point), so a cosine gate
# drops unrelated memories. With bge-small, unrelated short texts sit around 0.47-0.57.
RELEVANCE_FLOOR = 0.55
MMR_LAMBDA = 0.7
NEAR_DUPLICATE = 0.92


class MissingUser(ValueError):
    """Raised when user data is touched without a user id (AGENTS.md rule 7)."""


def _require(user_id: UUID | None) -> str:
    if not user_id:
        raise MissingUser("every memory operation on user data needs a user_id")
    return str(user_id)


def user_filter(user_id: UUID, *extra: models.Condition) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(key="user_id", match=models.MatchValue(value=_require(user_id))),
            *extra,
        ]
    )


@dataclass(frozen=True)
class KnowledgeHit:
    id: str
    text: str
    dim: str | None
    source: str
    evidence_level: str | None
    score: float


@dataclass
class _Candidate:
    point: Any
    collection: Literal["episodic", "facts"]
    score: float


def _cos(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _dense(point: Any) -> list[float]:
    vectors: dict[str, list[float]] = point.vector
    return vectors["dense"]


def mmr(candidates: list[_Candidate], limit: int, lam: float = MMR_LAMBDA) -> list[_Candidate]:
    """Maximal marginal relevance over dense vectors."""
    if not candidates:
        return []
    top = max(c.score for c in candidates) or 1.0
    chosen: list[_Candidate] = []
    pool = list(candidates)
    while pool and len(chosen) < limit:

        def redundancy(c: _Candidate) -> float:
            vec = _dense(c.point)
            return max((_cos(vec, _dense(s.point)) for s in chosen), default=0.0)

        # Near-copies of something already picked are skipped outright (same threshold that
        # consolidation uses to merge them).
        pool = [c for c in pool if redundancy(c) <= NEAR_DUPLICATE]
        if not pool:
            break
        best = max(pool, key=lambda c: lam * (c.score / top) - (1 - lam) * redundancy(c))
        chosen.append(best)
        pool.remove(best)
    return chosen


class MemoryStore:
    def __init__(self, client: AsyncQdrantClient, embedder: Embedder, prefix: str = "") -> None:
        self._client = client
        self.embedder = embedder
        self.prefix = prefix

    def name(self, collection: str) -> str:
        return f"{self.prefix}{collection}"

    # Setup -------------------------------------------------------------------------------

    async def ensure_collections(self) -> None:
        for collection in (*USER_COLLECTIONS, KNOWLEDGE):
            name = self.name(collection)
            if await self._client.collection_exists(name):
                continue
            sparse = (
                {"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)}
                if collection != "exercises"
                else None
            )
            await self._client.create_collection(
                name,
                vectors_config={
                    "dense": models.VectorParams(size=DENSE_SIZE, distance=models.Distance.COSINE)
                },
                sparse_vectors_config=sparse,
            )
            if collection == KNOWLEDGE:
                await self._client.create_payload_index(
                    name, "dim", models.PayloadSchemaType.KEYWORD
                )
                continue
            await self._client.create_payload_index(
                name,
                "user_id",
                models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, is_tenant=True),
            )
            for field, schema in (
                ("kind", models.PayloadSchemaType.KEYWORD),
                ("dims", models.PayloadSchemaType.KEYWORD),
                ("created_at", models.PayloadSchemaType.DATETIME),
                ("importance", models.PayloadSchemaType.FLOAT),
                ("game_id", models.PayloadSchemaType.KEYWORD),
                ("served_at", models.PayloadSchemaType.DATETIME),
            ):
                await self._client.create_payload_index(name, field, schema)

    async def drop_collections(self) -> None:
        for collection in (*USER_COLLECTIONS, KNOWLEDGE):
            await self._client.delete_collection(self.name(collection))

    # Writes ------------------------------------------------------------------------------

    async def write(
        self,
        user_id: UUID,
        text: str,
        *,
        collection: Literal["episodic", "facts"] = "episodic",
        kind: str = "moment",
        importance: float = 0.5,
        dims: Sequence[str] = (),
        source_event_ids: Sequence[UUID] = (),
        confidence: float | None = None,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
        point_id: UUID | None = None,
        extra: dict[str, Any] | None = None,
    ) -> UUID:
        uid = _require(user_id)
        [emb] = await self.embedder.embed([text])
        pid = point_id or uuid.uuid4()
        payload: dict[str, Any] = {
            "user_id": uid,
            "text": text,
            "kind": kind,
            "importance": max(0.0, min(1.0, importance)),
            "dims": list(dims),
            "source_event_ids": [str(e) for e in source_event_ids],
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
        }
        if extra:
            payload.update(extra)
        if collection == "facts":
            payload.update(
                confidence=confidence if confidence is not None else 0.5,
                valid_from=payload["created_at"],
                valid_to=None,
                superseded_by=None,
            )
        await self._client.upsert(
            self.name(collection),
            points=[
                models.PointStruct(
                    id=str(pid),
                    vector={
                        "dense": emb.dense,
                        "sparse": models.SparseVector(
                            indices=emb.sparse_indices, values=emb.sparse_values
                        ),
                    },
                    payload=payload,
                )
            ],
        )
        return pid

    async def set_payload(
        self, user_id: UUID, collection: UserCollection, point_id: UUID, payload: dict[str, Any]
    ) -> None:
        await self._client.set_payload(
            self.name(collection),
            payload=payload,
            points=models.FilterSelector(
                filter=user_filter(user_id, models.HasIdCondition(has_id=[str(point_id)]))
            ),
        )

    async def delete_points(
        self, user_id: UUID, collection: UserCollection, point_ids: Sequence[UUID]
    ) -> None:
        if not point_ids:
            return
        await self._client.delete(
            self.name(collection),
            points_selector=models.FilterSelector(
                filter=user_filter(
                    user_id, models.HasIdCondition(has_id=[str(p) for p in point_ids])
                )
            ),
        )

    async def delete_user(self, user_id: UUID) -> dict[str, int]:
        """Delete every point of this user in every collection; returns counts per collection."""
        counts: dict[str, int] = {}
        for collection in USER_COLLECTIONS:
            name = self.name(collection)
            counts[collection] = (
                await self._client.count(name, count_filter=user_filter(user_id), exact=True)
            ).count
            await self._client.delete(
                name, points_selector=models.FilterSelector(filter=user_filter(user_id))
            )
        return counts

    # Reads -------------------------------------------------------------------------------

    async def points(
        self, user_id: UUID, collection: UserCollection, *, with_vectors: bool = False
    ) -> list[Any]:
        """All of one user's points in a collection (consolidation, export)."""
        out: list[Any] = []
        offset = None
        while True:
            batch, offset = await self._client.scroll(
                self.name(collection),
                scroll_filter=user_filter(user_id),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=["dense"] if with_vectors else False,
            )
            out.extend(batch)
            if offset is None:
                return out

    async def get(self, user_id: UUID, collection: UserCollection, point_id: UUID) -> Any | None:
        found, _ = await self._client.scroll(
            self.name(collection),
            scroll_filter=user_filter(user_id, models.HasIdCondition(has_id=[str(point_id)])),
            limit=1,
            with_payload=True,
        )
        return found[0] if found else None

    async def recall(
        self,
        user_id: UUID,
        query: str,
        *,
        limit: int = 5,
        collections: Sequence[Literal["episodic", "facts"]] = ("episodic", "facts"),
        now: datetime | None = None,
    ) -> list[MemoryHit]:
        flt = user_filter(user_id)
        now = now or datetime.now(UTC)
        q = await self.embedder.embed_query(query)
        candidates: list[_Candidate] = []
        top_fused = 0.0
        for collection in collections:
            response = await self._client.query_points(
                self.name(collection),
                prefetch=[
                    models.Prefetch(query=q.dense, using="dense", filter=flt, limit=PREFETCH),
                    models.Prefetch(
                        query=models.SparseVector(indices=q.sparse_indices, values=q.sparse_values),
                        using="sparse",
                        filter=flt,
                        limit=PREFETCH,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=flt,
                limit=PREFETCH,
                with_payload=True,
                with_vectors=["dense"],
            )
            top_fused = max([top_fused, *(p.score for p in response.points)])
            for point in response.points:
                payload = point.payload or {}
                if payload.get("superseded_by"):
                    continue
                expires = payload.get("expires_at")
                if expires and datetime.fromisoformat(expires) < now:
                    continue
                cos = _cos(q.dense, _dense(point))
                gate = min(1.0, max(0.0, (cos - RELEVANCE_FLOOR) / (1.0 - RELEVANCE_FLOOR)))
                if gate == 0.0:
                    continue
                age = (now - datetime.fromisoformat(payload["created_at"])).total_seconds() / 86_400
                decay = DECAY_FLOOR + (1 - DECAY_FLOOR) * math.exp(-max(age, 0.0) / DECAY_DAYS)
                weight = float(payload.get("confidence", payload.get("importance", 0.5)) or 0.0)
                score = point.score * gate * weight * decay
                candidates.append(_Candidate(point, collection, score))
        candidates.sort(key=lambda c: c.score, reverse=True)
        return [
            MemoryHit(
                point_id=UUID(str(c.point.id)),
                collection=c.collection,
                text=c.point.payload["text"],
                score=c.score,
                created_at=datetime.fromisoformat(c.point.payload["created_at"]),
                importance=float(c.point.payload.get("importance", 0.5)),
                source_event_ids=[UUID(e) for e in c.point.payload.get("source_event_ids", [])],
            )
            for c in mmr(candidates, limit)
        ]

    # Exercises (novelty checks, docs/plan/08) --------------------------------------------

    async def record_served(
        self, user_id: UUID, game_id: str, level: float, item_id: UUID, text: str
    ) -> None:
        [emb] = await self.embedder.embed([text])
        await self._client.upsert(
            self.name("exercises"),
            points=[
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector={"dense": emb.dense},
                    payload={
                        "user_id": _require(user_id),
                        "game_id": game_id,
                        "level": level,
                        "item_id": str(item_id),
                        "served_at": datetime.now(UTC).isoformat(),
                    },
                )
            ],
        )

    async def max_similarity_served(
        self, user_id: UUID, game_id: str, text: str, since: datetime
    ) -> float:
        q = await self.embedder.embed_query(text)
        flt = user_filter(
            user_id,
            models.FieldCondition(key="game_id", match=models.MatchValue(value=game_id)),
            models.FieldCondition(key="served_at", range=models.DatetimeRange(gte=since)),
        )
        response = await self._client.query_points(
            self.name("exercises"), query=q.dense, using="dense", query_filter=flt, limit=1
        )
        return response.points[0].score if response.points else 0.0

    # Knowledge (shared, no user data) -----------------------------------------------------

    async def load_knowledge(self, items: Sequence[dict[str, Any]]) -> int:
        texts = [i["text"] for i in items]
        embs = await self.embedder.embed(texts)
        await self._client.upsert(
            self.name(KNOWLEDGE),
            points=[
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"lodestar-knowledge/{item['id']}")),
                    vector={
                        "dense": e.dense,
                        "sparse": models.SparseVector(
                            indices=e.sparse_indices, values=e.sparse_values
                        ),
                    },
                    payload={
                        k: item.get(k) for k in ("id", "text", "dim", "source", "evidence_level")
                    },
                )
                for item, e in zip(items, embs, strict=True)
            ],
        )
        return len(items)

    async def search_knowledge(
        self, query: str, *, dim: str | None = None, limit: int = 3
    ) -> list[KnowledgeHit]:
        """The only query without a user filter: the knowledge collection holds no user data."""
        q = await self.embedder.embed_query(query)
        flt = (
            models.Filter(
                must=[models.FieldCondition(key="dim", match=models.MatchValue(value=dim))]
            )
            if dim
            else None
        )
        response = await self._client.query_points(
            self.name(KNOWLEDGE), query=q.dense, using="dense", query_filter=flt, limit=limit
        )
        return [
            KnowledgeHit(
                id=p.payload["id"],
                text=p.payload["text"],
                dim=p.payload.get("dim"),
                source=p.payload.get("source", ""),
                evidence_level=p.payload.get("evidence_level"),
                score=p.score,
            )
            for p in response.points
            if p.payload
        ]
