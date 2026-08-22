"""HTTP surface for ingest + cast registry. Export `router`; the conductor
mounts it in backend/app.py (see backend/ingest/README.md) — this module does
NOT mount itself.

Response conventions match the mock: not-found returns the `{"error": {...}}`
JSON body, people docs are the mock's shape (plus additive fields like
embeddings/refSpecs the panel is free to ignore).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.ws import hub
from backend.db.store import MOCK_PROJECT_ID, get_store
from backend.ingest.analyzers import choose_analyzers
from backend.ingest.pipeline import ingest_footage

router = APIRouter()

# In-process ingest status, mirroring the mock's JOBS dict. Ingest history is
# not project data worth persisting tonight; the people it creates are.
INGESTS: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _not_found(ref: str) -> dict[str, Any]:
    return {"error": {"code": "not_found", "message": ref}}


# ---------------------------------------------------------------- people


@router.get("/people")
async def list_people(projectId: str = MOCK_PROJECT_ID) -> list[dict[str, Any]]:
    store = await get_store()
    return await store.people.list(projectId)


class PolicyUpdate(BaseModel):
    policy: str  # approved | unknown | remove
    name: str | None = None


@router.post("/people/{person_id}/policy")
async def set_policy(person_id: str, body: PolicyUpdate) -> dict[str, Any]:
    store = await get_store()
    person = await store.people.set_policy(person_id, body.policy, body.name)
    return person or _not_found(person_id)


# ---------------------------------------------------------------- ingest


class IngestRequest(BaseModel):
    projectId: str = MOCK_PROJECT_ID
    path: str


async def _run_ingest(ingest_id: str) -> None:
    status = INGESTS[ingest_id]
    store = await get_store()
    try:
        summary = await ingest_footage(
            status["projectId"],
            status["path"],
            analyzers=choose_analyzers(),  # RUSHCUT_ANALYZERS=real|fake, default fake
            people_repo=store.people,
            emit_log=hub.log,  # progress lines reach every connected panel
            ingest_id=ingest_id,
        )
        status.update(state="complete", summary=summary, finishedAt=_now())
    except Exception as exc:  # noqa: BLE001 — status must record any failure
        status.update(
            state="failed",
            error={"code": "ingest_failed", "message": str(exc)},
            finishedAt=_now(),
        )
        await hub.log(ingest_id, f"ingest failed: {exc}")


@router.post("/ingest/footage")
async def start_ingest(body: IngestRequest) -> dict[str, Any]:
    ingest_id = f"ing_{uuid.uuid4().hex[:12]}"
    INGESTS[ingest_id] = {
        "ingestId": ingest_id,
        "projectId": body.projectId,
        "path": body.path,
        "state": "running",
        "summary": None,
        "error": None,
        "startedAt": _now(),
        "finishedAt": None,
    }
    asyncio.create_task(_run_ingest(ingest_id))
    return {"ingestId": ingest_id}


@router.get("/ingest/{ingest_id}")
async def ingest_status(ingest_id: str) -> dict[str, Any]:
    return INGESTS.get(ingest_id) or _not_found(ingest_id)
