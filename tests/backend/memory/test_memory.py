import inspect
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.memory.consolidate import consolidate_user, merge_duplicates
from backend.memory.langgraph_store import QdrantStore
from backend.memory.notes import Notes
from backend.memory.store import MemoryStore, MissingUser
from backend.registry.loader import load_knowledge_items

NOW = datetime.now(UTC)


def test_every_user_data_method_requires_a_user_id() -> None:
    """AGENTS.md rule 7: no way to query user data without naming the user."""
    shared = {
        "name",
        "ensure_collections",
        "drop_collections",
        "load_knowledge",
        "search_knowledge",
    }
    for name, fn in inspect.getmembers(MemoryStore, inspect.isfunction):
        if name.startswith("_") or name in shared:
            continue
        params = list(inspect.signature(fn).parameters)
        assert params[1] == "user_id", name
    assert not any(n == "client" for n in vars(MemoryStore))


async def test_search_without_a_user_is_impossible(memory: MemoryStore) -> None:
    with pytest.raises(MissingUser):
        await memory.recall(None, "anything")  # type: ignore[arg-type]
    with pytest.raises(MissingUser):
        await memory.write(None, "text")  # type: ignore[arg-type]


async def test_users_never_see_each_other(memory: MemoryStore) -> None:
    alice, bob = uuid4(), uuid4()
    await memory.write(alice, "I have exams next week", kind="self_statement", importance=0.9)
    assert await memory.recall(bob, "exams next week") == []
    assert [h.text for h in await memory.recall(alice, "exams")] == ["I have exams next week"]


async def test_recent_relevant_memory_ranks_above_an_old_one(memory: MemoryStore) -> None:
    user = uuid4()
    await memory.write(user, "Felt tired during the evening memory games", importance=0.6,
                       created_at=NOW - timedelta(days=60))  # fmt: skip
    await memory.write(user, "Tired in the evening memory session again", importance=0.6,
                       created_at=NOW - timedelta(days=1))  # fmt: skip
    await memory.write(user, "Likes football", importance=0.6, created_at=NOW)
    hits = await memory.recall(user, "tired evening memory", limit=3)
    assert hits[0].text == "Tired in the evening memory session again"
    assert hits[1].text == "Felt tired during the evening memory games"


async def test_mmr_avoids_near_copies(memory: MemoryStore) -> None:
    user = uuid4()
    for i in range(3):
        await memory.write(user, f"Prefers fewer timed games{'!' * i}", importance=0.8)
    await memory.write(user, "Prefers games without a timer in the morning", importance=0.5)
    texts = [h.text for h in await memory.recall(user, "prefers timed games", limit=2)]
    assert "Prefers games without a timer in the morning" in texts


async def test_dedupe_merges_near_duplicates(memory: MemoryStore) -> None:
    user = uuid4()
    e1, e2 = uuid4(), uuid4()
    await memory.write(user, "I have exams next week", importance=0.6, source_event_ids=[e1],
                       created_at=NOW - timedelta(hours=2))  # fmt: skip
    await memory.write(user, "I have my exams next week", importance=0.9, source_event_ids=[e2])
    await memory.write(user, "Plays mostly at 21:00", importance=0.5)
    assert await merge_duplicates(memory, user, "episodic") == 1
    points = {p.payload["text"]: p.payload for p in await memory.points(user, "episodic")}
    merged = points["I have my exams next week"]
    assert merged["count"] == 2 and merged["importance"] == 0.9
    assert set(merged["source_event_ids"]) == {str(e1), str(e2)}
    assert "Plays mostly at 21:00" in points


async def test_consolidation_promotes_facts_and_rewrites_core(
    memory: MemoryStore, tmp_path: Path
) -> None:
    user = uuid4()
    notes = Notes(tmp_path)
    pref = {"kind": "preference", "importance": 0.9}
    await memory.write(user, 'Said: "I prefer fewer timed games"', **pref,  # type: ignore[arg-type]
                       created_at=NOW - timedelta(days=1))  # fmt: skip
    await memory.write(user, 'Said: "I prefer fewer timed games please"', kind="preference",
                       importance=0.9)  # fmt: skip
    await memory.write(
        user, "Old routine note", importance=0.5, created_at=NOW - timedelta(days=45)
    )
    await memory.write(user, "Exam tomorrow", importance=0.7, expires_at=NOW - timedelta(hours=1))
    report = await consolidate_user(
        memory, notes, user, summary="Session on 21 Oct: played Echo.",
        header_lines=["Prefers the Willow coach"], now=NOW,
    )  # fmt: skip
    assert (
        report.merged == 1 and report.promoted == 1 and report.expired == 1 and report.decayed == 1
    )
    core = notes.read_core(user)
    assert core[0] == "Prefers the Willow coach" and "timed games" in core[1]
    assert "played Echo" in (notes.read_journal(user, NOW.date()) or "")
    facts = await memory.points(user, "facts")
    assert len(facts) == 1 and 0.6 <= facts[0].payload["confidence"] <= 0.9


async def test_delete_user_removes_every_point(memory: MemoryStore) -> None:
    user, other = uuid4(), uuid4()
    await memory.write(user, "one")
    await memory.write(user, "two", collection="facts", confidence=0.7)
    await memory.write(other, "keep me")
    counts = await memory.delete_user(user)
    assert counts["episodic"] == 1 and counts["facts"] == 1
    assert await memory.points(user, "episodic") == [] and await memory.points(user, "facts") == []
    assert len(await memory.points(other, "episodic")) == 1


async def test_langgraph_store_interface(memory: MemoryStore) -> None:
    store = QdrantStore(memory)
    user = str(uuid4())
    ns = ("users", user, "episodic")
    await store.aput(ns, "m1", {"text": "Said she prefers fewer timed games", "kind": "preference",
                                "importance": 0.8})  # fmt: skip
    item = await store.aget(ns, "m1")
    assert item is not None and item.value["text"].startswith("Said she prefers")
    hits = await store.asearch(ns, query="timed games")
    assert hits and hits[0].value["text"].startswith("Said she prefers")
    await store.adelete(ns, "m1")
    assert await store.aget(ns, "m1") is None
    with pytest.raises(MissingUser):
        await store.asearch(("everyone",), query="x")


async def test_knowledge_is_shared_and_filterable(memory: MemoryStore) -> None:
    assert await memory.load_knowledge(load_knowledge_items()) == 6
    hits = await memory.search_knowledge("how do I remember a long list", limit=2)
    assert hits and hits[0].id == "K-chunking"
    only = await memory.search_knowledge("focus", dim="sustained_attention")
    assert {h.dim for h in only} == {"sustained_attention"}


async def test_novelty_check_finds_recently_served_items(memory: MemoryStore) -> None:
    user = uuid4()
    await memory.record_served(user, "market_rush", 0.4, uuid4(), "Two kilos of oranges and chilli")
    since = NOW - timedelta(days=30)
    same = await memory.max_similarity_served(
        user, "market_rush", "Two kilos of oranges and chilli", since
    )
    other_user = await memory.max_similarity_served(
        uuid4(), "market_rush", "Two kilos of oranges", since
    )
    assert same > 0.9 and other_user == 0.0


def test_notes_are_atomic_and_deletable(tmp_path: Path) -> None:
    notes = Notes(tmp_path)
    user = UUID(int=7)
    notes.write_core(user, ["Prefers the Willow persona", "Usually plays in the evening"])
    assert notes.remove_core_line(user, "Usually plays in the evening")
    assert notes.read_core(user) == ["Prefers the Willow persona"]
    notes.append_journal(user, date(2026, 10, 21), "Played Echo.")
    assert not list(tmp_path.rglob("*.tmp"))
    assert notes.delete_user(user) == 2 and not (tmp_path / str(user)).exists()
