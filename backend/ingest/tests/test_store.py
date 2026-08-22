"""In-memory store: seeding, policy persistence, projectId isolation."""

from __future__ import annotations

import asyncio

import pytest

from backend.db.store import MOCK_PROJECT_ID, memory_store


def test_seeds_and_set_policy_persists() -> None:
    async def run() -> None:
        store = memory_store()
        people = await store.people.list(MOCK_PROJECT_ID)
        assert [p["_id"] for p in people] == ["per_dana", "per_marcus", "per_unknown_1"]
        assert people[0]["policy"] == "approved"
        assert people[0]["faceEmbeddings"], "seeded principals carry demo embeddings"

        updated = await store.people.set_policy(
            "per_unknown_1", "approved", name="Riley"
        )
        assert (
            updated is not None
            and updated["policy"] == "approved"
            and updated["name"] == "Riley"
        )
        # Persisted, not just returned.
        again = await store.people.get("per_unknown_1")
        assert (
            again is not None
            and again["policy"] == "approved"
            and again["name"] == "Riley"
        )

    asyncio.run(run())


def test_project_isolation() -> None:
    async def run() -> None:
        store = memory_store()
        a = await store.people.list("proj_a")
        b = await store.people.list("proj_b")
        # Both projects get their own seeds with non-colliding ids.
        assert len(a) == len(b) == 3
        assert {p["_id"] for p in a}.isdisjoint({p["_id"] for p in b})

        await store.people.upsert(
            {"projectId": "proj_a", "name": "Zed", "policy": "unknown"}
        )
        assert any(p["name"] == "Zed" for p in await store.people.list("proj_a"))
        assert not any(p["name"] == "Zed" for p in await store.people.list("proj_b"))

        # Policy flips in one project never leak into the other.
        dana_a = next(p for p in a if p["name"] == "Dana")
        await store.people.set_policy(dana_a["_id"], "remove")
        dana_b = next(
            p for p in await store.people.list("proj_b") if p["name"] == "Dana"
        )
        assert dana_b["policy"] == "approved"

    asyncio.run(run())


def test_every_document_carries_project_id() -> None:
    async def run() -> None:
        store = memory_store()
        with pytest.raises(ValueError):
            await store.people.upsert({"name": "nobody"})
        with pytest.raises(ValueError):
            await store.generations.record({"jobId": "job_x"})

    asyncio.run(run())


def test_generations_and_notes() -> None:
    async def run() -> None:
        store = memory_store()
        doc = await store.generations.record(
            {
                "projectId": "proj_a",
                "jobId": "job_1",
                "model": "wan2.2_ti2v_5B",
                "seed": 7,
            }
        )
        assert doc["_id"].startswith("gen_")
        assert len(await store.generations.list("proj_a")) == 1
        assert await store.generations.list("proj_b") == []

        await store.notes.add("proj_a", "Dana prefers the low-angle lobby shot")
        assert (
            len(await store.notes.search_text("proj_a", "LOBBY")) == 1
        )  # case-insensitive
        assert await store.notes.search_text("proj_a", "rooftop") == []
        assert await store.notes.search_text("proj_b", "lobby") == []

    asyncio.run(run())
