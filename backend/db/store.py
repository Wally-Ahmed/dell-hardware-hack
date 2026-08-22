"""Storage for the cast registry, generations and notes (docs/api.md §5).

Graceful degradation is the design: try MongoDB via motor (1 s server-selection
timeout), and on ANY failure fall back to an in-memory store with the exact
same async interface. The repos are written once against a tiny collection
shim, so the Mongo and memory paths share every line of business logic —
there is no second implementation to drift.

Embeddings are plain lists on the person doc (`faceEmbeddings[]`,
`bodyEmbeddings[]`) and matching is brute-force cosine in numpy — the
contract's pragmatic call: no vector search node tonight.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from typing import Any, Protocol

from backend.core.config import settings

# The mock's project — seeded with the mock's exact person ids so the cast
# panel sees byte-identical data whether it talks to the mock or to us.
MOCK_PROJECT_ID = "proj_01J8W_atlas"

# Demo fixture embeddings for the seeded principals. Deliberately tiny (8-dim)
# and axis-aligned: obviously synthetic (nobody mistakes them for biometrics),
# orthogonal across identities (cosine 0), and cheap to eyeball in tests. The
# fake analyzers emit noisy copies of these so the off-box demo reproduces the
# beat "2 match approved cast". On the GB10, InsightFace appends real 512-dim
# vectors; the pipeline skips stored vectors whose dimension doesn't match a
# query, so the two generations coexist without crashing.
DANA_FACE: list[float] = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
MARCUS_FACE: list[float] = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _oid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def seed_people(project_id: str) -> list[dict[str, Any]]:
    """The mock's three canned people, stamped with `project_id`.

    Ids match the mock exactly for the mock's project; other projects get a
    suffixed id because `_id` must stay unique across projects in one
    collection (multi-project is nearly free today, painful tomorrow).
    """
    suffix = (
        ""
        if project_id == MOCK_PROJECT_ID
        else f"_{uuid.uuid5(uuid.NAMESPACE_URL, project_id).hex[:6]}"
    )
    return [
        {
            "_id": f"per_dana{suffix}",
            "projectId": project_id,
            "name": "Dana",
            "role": "principal",
            "policy": "approved",
            "refs": {
                "face": "/media/refs/dana_face.jpg",
                "body": "/media/refs/dana_body.jpg",
                "wardrobe": "/media/refs/dana_wardrobe.jpg",
            },
            "consent": {
                "recordUrl": "/media/consent/dana_signed.pdf",
                "scope": "Project Atlas — corporate brand film, all media, 2 years",
                "noticeAt": "2026-08-20T09:00:00Z",
                "signedAt": "2026-08-22T08:15:00Z",
                "revokedAt": None,
            },
            "faceEmbeddings": [list(DANA_FACE)],
            "bodyEmbeddings": [],
        },
        {
            "_id": f"per_marcus{suffix}",
            "projectId": project_id,
            "name": "Marcus",
            "role": "principal",
            "policy": "approved",
            "refs": {
                "face": "/media/refs/marcus_face.jpg",
                "body": "/media/refs/marcus_body.jpg",
                "wardrobe": "/media/refs/marcus_wardrobe.jpg",
            },
            "consent": {
                "recordUrl": "/media/consent/marcus_signed.pdf",
                "scope": "Project Atlas — corporate brand film, all media, 2 years",
                "noticeAt": "2026-08-20T09:00:00Z",
                "signedAt": "2026-08-22T08:20:00Z",
                "revokedAt": None,
            },
            "faceEmbeddings": [list(MARCUS_FACE)],
            "bodyEmbeddings": [],
        },
        {
            # The demo beat: an unknown face the human must approve or remove.
            # No embeddings on purpose — it was flagged without usable vectors,
            # so it never participates in matching.
            "_id": f"per_unknown_1{suffix}",
            "projectId": project_id,
            "name": None,
            "role": "background",
            "policy": "unknown",
            "refs": {
                "face": "/media/refs/unknown_1_face.jpg",
                "body": "/media/refs/unknown_1_body.jpg",
                "wardrobe": None,
            },
            "consent": None,
            "faceEmbeddings": [],
            "bodyEmbeddings": [],
        },
    ]


# ---------------------------------------------------------------- collection shim


class Collection(Protocol):
    """The five motor calls the repos use — the memory shim implements the same."""

    def find(self, flt: dict[str, Any]) -> Any: ...
    async def find_one(self, flt: dict[str, Any]) -> dict[str, Any] | None: ...
    async def insert_one(self, doc: dict[str, Any]) -> Any: ...
    async def replace_one(
        self, flt: dict[str, Any], doc: dict[str, Any], upsert: bool = False
    ) -> Any: ...
    async def update_one(self, flt: dict[str, Any], update: dict[str, Any]) -> Any: ...


class _MemoryCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return self._docs if length is None else self._docs[:length]


class MemoryCollection:
    """Equality-filter subset of a motor collection, enough for tonight.

    Documents are deep-copied on the way in and out so callers can't mutate
    stored state behind the repo's back — the same isolation Mongo gives us.
    """

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _matches(doc: dict[str, Any], flt: dict[str, Any]) -> bool:
        return all(doc.get(k) == v for k, v in flt.items())

    def find(self, flt: dict[str, Any]) -> _MemoryCursor:
        hits = [copy.deepcopy(d) for d in self._docs.values() if self._matches(d, flt)]
        return _MemoryCursor(hits)

    async def find_one(self, flt: dict[str, Any]) -> dict[str, Any] | None:
        for d in self._docs.values():
            if self._matches(d, flt):
                return copy.deepcopy(d)
        return None

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self._docs[doc["_id"]] = copy.deepcopy(doc)

    async def replace_one(
        self, flt: dict[str, Any], doc: dict[str, Any], upsert: bool = False
    ) -> None:
        for _id, d in self._docs.items():
            if self._matches(d, flt):
                self._docs[_id] = copy.deepcopy(doc)
                return
        if upsert:
            self._docs[doc["_id"]] = copy.deepcopy(doc)

    async def update_one(self, flt: dict[str, Any], update: dict[str, Any]) -> None:
        for d in self._docs.values():
            if self._matches(d, flt):
                for k, v in update.get("$set", {}).items():
                    d[k] = copy.deepcopy(v)
                return


# ---------------------------------------------------------------- repos


class PeopleRepo:
    """The cast registry. Every read seeds the mock's three when empty so the
    Cast panel is never blank — the demo starts from a believable project."""

    def __init__(self, col: Collection) -> None:
        self._col = col

    async def list(self, project_id: str) -> list[dict[str, Any]]:
        docs = await self._col.find({"projectId": project_id}).to_list(None)
        if not docs:
            for person in seed_people(project_id):
                await self._col.replace_one({"_id": person["_id"]}, person, upsert=True)
            docs = await self._col.find({"projectId": project_id}).to_list(None)
        docs.sort(key=lambda d: str(d["_id"]))  # deterministic panel order
        return docs

    async def get(self, person_id: str) -> dict[str, Any] | None:
        return await self._col.find_one({"_id": person_id})

    async def upsert(self, person: dict[str, Any]) -> dict[str, Any]:
        if "projectId" not in person:
            # Contract §5: every document carries projectId from the first write.
            raise ValueError("person document must carry projectId")
        person.setdefault("_id", _oid("per"))
        person.setdefault("faceEmbeddings", [])
        person.setdefault("bodyEmbeddings", [])
        await self._col.replace_one({"_id": person["_id"]}, person, upsert=True)
        return person

    async def set_policy(
        self, person_id: str, policy: str, name: str | None = None
    ) -> dict[str, Any] | None:
        fields: dict[str, Any] = {"policy": policy}
        if name:
            fields["name"] = name
        await self._col.update_one({"_id": person_id}, {"$set": fields})
        return await self._col.find_one({"_id": person_id})


class GenerationsRepo:
    """Provenance blocks from §2, one doc per generated asset."""

    def __init__(self, col: Collection) -> None:
        self._col = col

    async def record(self, provenance_doc: dict[str, Any]) -> dict[str, Any]:
        if "projectId" not in provenance_doc:
            raise ValueError("generation document must carry projectId")
        provenance_doc.setdefault("_id", _oid("gen"))
        await self._col.insert_one(provenance_doc)
        return provenance_doc

    async def list(self, project_id: str) -> list[dict[str, Any]]:
        return await self._col.find({"projectId": project_id}).to_list(None)


class NotesRepo:
    """Free-text project memory. Search is naive substring for tonight —
    nomic-embed-text vectors slot into `embedding` on the box later."""

    def __init__(self, col: Collection) -> None:
        self._col = col

    async def add(
        self, project_id: str, text: str, embedding: list[float] | None = None
    ) -> dict[str, Any]:
        doc = {
            "_id": _oid("note"),
            "projectId": project_id,
            "text": text,
            "embedding": embedding,
        }
        await self._col.insert_one(doc)
        return doc

    async def search_text(self, project_id: str, query: str) -> list[dict[str, Any]]:
        docs = await self._col.find({"projectId": project_id}).to_list(None)
        needle = query.lower()
        return [d for d in docs if needle in str(d.get("text", "")).lower()]


# ---------------------------------------------------------------- store


class Store:
    def __init__(
        self,
        people_col: Collection,
        gen_col: Collection,
        notes_col: Collection,
        backend: str,
    ) -> None:
        self.people = PeopleRepo(people_col)
        self.generations = GenerationsRepo(gen_col)
        self.notes = NotesRepo(notes_col)
        self.backend = (
            backend  # "mongo" | "memory" — surfaced in /health-style debugging
        )


def memory_store() -> Store:
    """A fresh, isolated in-memory store. Tests use this directly."""
    return Store(
        MemoryCollection(), MemoryCollection(), MemoryCollection(), backend="memory"
    )


async def open_store(mongo_uri: str | None = None) -> Store:
    """Mongo if it answers a ping within 1 s, otherwise memory. Never raises —
    the demo must not die because mongod isn't up on somebody's laptop."""
    uri = mongo_uri or settings.mongo_uri
    try:
        from motor.motor_asyncio import AsyncIOMotorClient  # optional dep, lazy

        client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=1000)
        await client.admin.command("ping")
        db = client.get_default_database("rushcut")
        return Store(db["people"], db["generations"], db["notes"], backend="mongo")
    except Exception as exc:  # noqa: BLE001 — any failure means "no Mongo tonight"
        print(
            f"[db] mongo unavailable ({type(exc).__name__}: {exc}) — using in-memory store"
        )
        return memory_store()


_store: Store | None = None
_store_lock = asyncio.Lock()


async def get_store() -> Store:
    """Process-wide singleton for the routers; lock prevents a double open
    when two requests race on a cold start."""
    global _store
    if _store is None:
        async with _store_lock:
            if _store is None:
                _store = await open_store()
    return _store
