"""The real backend for docs/api.md. Supersedes backend/mock/app.py while
emitting identical frame shapes, so the frontend switches by doing nothing.

    uvicorn backend.app:app --reload --port 8000

RUSHCUT_EXECUTOR=simulated (default) walks jobs on a timer; =comfy drives the
GB10's ComfyUI. Not-found responses use the mock's `{"error": {...}}` JSON
body convention rather than 404s — every route returns JSON the panels can
render without a second error path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.core.config import settings
from backend.core.ws import hub
from backend.jobs.executor import get_executor
from backend.db.store import get_store
from backend.jobs.queue import JobQueue
from backend.jobs.state import new_job, oid
from backend.models.manager import ModelManager

PROJECT_ID = "proj_01J8W_atlas"
# The agent brain: resident and pinned from boot so no generative load can
# evict the model that is mid-conversation with the user.
BRAIN_MODEL = "qwen3-vl-30b-a3b"


def _not_found(ref: str) -> dict[str, Any]:
    return {"error": {"code": "not_found", "message": ref}}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    manager = ModelManager(simulate=settings.executor != "comfy")
    await manager.ensure(BRAIN_MODEL)
    await manager.pin(BRAIN_MODEL, True)
    queue = JobQueue(get_executor())
    queue.start()
    app.state.models = manager
    app.state.queue = queue
    app.state.sessions = {}
    yield
    await queue.stop()


app = FastAPI(title="AI-native NLE", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- jobs


class JobRequest(BaseModel):
    type: str
    projectId: str = PROJECT_ID
    params: dict[str, Any] = {}


async def _pre_gpu_cast_gate(req: JobRequest) -> dict[str, Any] | None:
    """Consent check BEFORE the GPU ever runs. The post-generation check on
    output stays authoritative; this one refuses to spend a 3-6 minute render
    on a request that already references an unapproved or unknown person.
    Only person refs (per_*) are gated — asset refs are not people."""
    person_refs = [r for r in (req.params.get("references") or []) if str(r).startswith("per_")]
    if not person_refs:
        return None
    store = await get_store()
    # list() seeds the demo people on a fresh store; get() alone would see an
    # empty registry on the first request of the process and block everyone.
    await store.people.list(req.projectId)
    unapproved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for ref in person_refs:
        person = await store.people.get(ref)
        if person is None:
            # Missing from the registry is unresolved, and unresolved never
            # auto-passes — same rule as the output check.
            unresolved.append({"trackId": ref, "reason": "not in cast registry", "cropUrl": None})
        elif person.get("policy") != "approved":
            unapproved.append(
                {"trackId": ref, "personId": ref, "confidence": 1.0, "frames": [], "cropUrl": None}
            )
    if not unapproved and not unresolved:
        return None
    job = new_job(req.type, req.projectId, req.params)
    job.update(
        state="policy_blocked",
        stage="policy_check",
        finishedAt=job["createdAt"],
        message="blocked before generation: request references non-approved people",
        policy={
            "verdict": "blocked",
            "unapproved": unapproved,
            "unresolved": unresolved,
            "remediation": None,
            "remediatedAssetId": None,
        },
    )
    return job


@app.post("/jobs")
async def create_job(req: JobRequest, request: Request) -> dict[str, Any]:
    blocked = await _pre_gpu_cast_gate(req)
    if blocked is not None:
        await request.app.state.queue.admit(blocked)
        return blocked
    return await request.app.state.queue.submit(req.type, req.projectId, req.params)


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    return request.app.state.queue.get(job_id) or _not_found(job_id)


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
    job = await request.app.state.queue.cancel(job_id)
    return job or _not_found(job_id)


@app.get("/jobs")
async def list_jobs(
    request: Request, projectId: str | None = None, state: str | None = None
) -> list[dict[str, Any]]:
    return request.app.state.queue.list(projectId, state)


# ---------------------------------------------------------------- models


@app.get("/models")
async def list_models(request: Request) -> list[dict[str, Any]]:
    return request.app.state.models.list()


@app.get("/models/budget")
async def model_budget(request: Request) -> dict[str, Any]:
    return request.app.state.models.budget()


class PinUpdate(BaseModel):
    pinned: bool


@app.post("/models/{model_id}/pin")
async def pin_model(model_id: str, body: PinUpdate, request: Request) -> dict[str, Any]:
    try:
        return await request.app.state.models.pin(model_id, body.pinned)
    except KeyError:
        return _not_found(model_id)


# ---------------------------------------------------------------- edit sessions
# In-memory and shaped exactly like the mock. Nothing reaches the working
# timeline except through review — that invariant lives here, not in the UI.


@app.post("/sessions")
async def open_session(request: Request, projectId: str = PROJECT_ID) -> dict[str, Any]:
    sid = oid("sess")
    request.app.state.sessions[sid] = {
        "sessionId": sid,
        "projectId": projectId,
        "ops": [],
        "applied": False,
    }
    return {"sessionId": sid}


@app.post("/sessions/{sid}/ops")
async def session_ops(
    sid: str, ops: list[dict[str, Any]], request: Request
) -> dict[str, Any]:
    s = request.app.state.sessions.get(sid)
    if not s:
        return {"ok": False, "staleIds": [], "error": "no such session"}
    s["ops"].extend(ops)
    return {"ok": True, "staleIds": []}


@app.get("/sessions/{sid}/preview")
async def session_preview(sid: str, request: Request) -> dict[str, Any]:
    s = request.app.state.sessions.get(sid, {})
    # Canned draft timeline (same ids as the mock) until Role C's timeline
    # store lands; pendingOps is the part the review flow actually needs.
    return {
        "sessionId": sid,
        "timeline": {
            "tracks": [
                {
                    "trackId": "trk_v1",
                    "kind": "video",
                    "clips": [
                        {
                            "clipId": "clp_1",
                            "assetId": "ast_lobby_wide",
                            "startMs": 0,
                            "durationMs": 4200,
                        },
                        {
                            "clipId": "clp_2",
                            "assetId": "ast_dana_med",
                            "startMs": 4200,
                            "durationMs": 3100,
                        },
                    ],
                }
            ]
        },
        "pendingOps": s.get("ops", []),
    }


@app.post("/sessions/{sid}/review")
async def session_review(sid: str, request: Request, apply: bool = True) -> dict[str, Any]:
    s = request.app.state.sessions.get(sid)
    if not s:
        return {"applied": False, "error": "no such session"}
    s["applied"] = apply
    return {"applied": apply, "undoLabel": f"Agent edit ({len(s['ops'])} ops)"}


# ---------------------------------------------------------------- people
# Role D's repo-backed cast endpoints (Mongo with in-memory fallback). The
# canned stub this replaced lives in backend/mock/app.py for contract reference.
from backend.ingest.router import router as ingest_router

app.include_router(ingest_router)

# Role E's chat surface. The loop only ever reaches the timeline through the
# same HTTP contract as the UI — no private back door.
from backend.agent.router import router as agent_router

app.include_router(agent_router)

# Render path: timeline JSON -> ffmpeg on the backend (the vendored editor's
# own export stays unused by design).
from backend.render.router import router as render_router

app.include_router(render_router)


# ---------------------------------------------------------------- websocket


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await hub.add(websocket)
    try:
        # A models frame on connect means the panel renders without waiting
        # for the first state change.
        await websocket.send_json(
            {"kind": "models", "models": websocket.app.state.models.list()}
        )
        while True:
            await websocket.receive_text()  # keepalive; clients send nothing meaningful
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(websocket)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "mock": False, "executor": settings.executor}
