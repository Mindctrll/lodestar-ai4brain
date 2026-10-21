"""LangGraph long-term store backed by Qdrant (docs/plan/03, "Persistence").

Namespaces are ("users", user_id, "episodic" | "facts"); the user id in the namespace becomes
the mandatory user filter. Nodes use `runtime.store` and never touch Qdrant directly.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)

from backend.memory.store import MemoryStore, MissingUser

Writable = Literal["episodic", "facts"]


def _parse(namespace: tuple[str, ...]) -> tuple[UUID, Writable]:
    if len(namespace) != 3 or namespace[0] != "users":
        raise MissingUser(
            f"namespace must be ('users', <user_id>, episodic|facts), got {namespace}"
        )
    if namespace[2] == "episodic":
        return UUID(namespace[1]), "episodic"
    if namespace[2] == "facts":
        return UUID(namespace[1]), "facts"
    raise MissingUser(f"unknown memory collection {namespace[2]!r}")


def point_id(namespace: tuple[str, ...], key: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, "najma-store/" + "/".join(namespace) + "/" + key)


def _item(namespace: tuple[str, ...], key: str, payload: dict[str, Any]) -> Item:
    created = datetime.fromisoformat(payload["created_at"])
    value = dict(payload.get("value") or {"text": payload["text"]})
    return Item(value=value, key=key, namespace=namespace, created_at=created, updated_at=created)


class QdrantStore(BaseStore):
    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        raise NotImplementedError("QdrantStore is async-only; the graph uses abatch")

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        results: list[Result] = []
        for op in ops:
            if isinstance(op, PutOp):
                await self._put(op)
                results.append(None)
            elif isinstance(op, GetOp):
                results.append(await self._get(op))
            elif isinstance(op, SearchOp):
                results.append(await self._search(op))
            elif isinstance(op, ListNamespacesOp):
                results.append([])  # namespaces are per user; listing all users isn't allowed
            else:  # pragma: no cover
                raise TypeError(f"unsupported op {type(op).__name__}")
        return results

    async def _put(self, op: PutOp) -> None:
        user_id, collection = _parse(op.namespace)
        pid = point_id(op.namespace, op.key)
        if op.value is None:
            await self.memory.delete_points(user_id, collection, [pid])
            return
        value = dict(op.value)
        await self.memory.write(
            user_id,
            str(value["text"]),
            collection=collection,
            kind=str(value.get("kind", "moment")),
            importance=float(value.get("importance", 0.5)),
            dims=list(value.get("dims", [])),
            source_event_ids=[UUID(str(e)) for e in value.get("source_event_ids", [])],
            confidence=value.get("confidence"),
            point_id=pid,
            extra={"key": op.key, "value": value},
        )

    async def _get(self, op: GetOp) -> Item | None:
        user_id, collection = _parse(op.namespace)
        point = await self.memory.get(user_id, collection, point_id(op.namespace, op.key))
        return _item(op.namespace, op.key, point.payload) if point else None

    async def _search(self, op: SearchOp) -> list[SearchItem]:
        user_id, collection = _parse(op.namespace_prefix)
        if not op.query:
            points = await self.memory.points(user_id, collection)
            items = [
                _item(op.namespace_prefix, p.payload.get("key", str(p.id)), p.payload)
                for p in points
            ]
            return [
                SearchItem(i.namespace, i.key, i.value, i.created_at, i.updated_at)
                for i in items[op.offset : op.offset + op.limit]
            ]
        hits = await self.memory.recall(
            user_id,
            op.query,
            limit=op.limit,
            collections=(collection,),
            now=datetime.now(UTC),
        )
        return [
            SearchItem(
                op.namespace_prefix,
                str(h.point_id),
                {"text": h.text, "importance": h.importance},
                h.created_at,
                h.created_at,
                score=h.score,
            )
            for h in hits
        ]
