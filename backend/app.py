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

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.core.config import settings
from backend.core.ws import hub
from backend.jobs.executor import get_executor
from backend.jobs.queue import JobQueue
from backend.jobs.state import oid
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


@app.post("/jobs")
async def create_job(req: JobRequest, request: Request) -> dict[str, Any]:
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
# Role D territory — thin stub until backend/ingest lands, same canned people
# as the mock, so the editor's cast panel keeps working today.

people_stub = APIRouter()

PEOPLE: list[dict[str, Any]] = [
    {
        "_id": "per_dana",
        "projectId": PROJECT_ID,
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
    },
    {
        "_id": "per_marcus",
        "projectId": PROJECT_ID,
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
    },
    {
        # The demo beat: an unknown face the human must approve or remove.
        "_id": "per_unknown_1",
        "projectId": PROJECT_ID,
        "name": None,
        "role": "background",
        "policy": "unknown",
        "refs": {
            "face": "/media/refs/unknown_1_face.jpg",
            "body": "/media/refs/unknown_1_body.jpg",
            "wardrobe": None,
        },
        "consent": None,
    },
]


class PolicyUpdate(BaseModel):
    policy: str  # approved | unknown | remove
    name: str | None = None


@people_stub.get("/people")
async def list_people(projectId: str = PROJECT_ID) -> list[dict[str, Any]]:
    return [p for p in PEOPLE if p["projectId"] == projectId]


@people_stub.post("/people/{person_id}/policy")
async def set_policy(person_id: str, body: PolicyUpdate) -> dict[str, Any]:
    for p in PEOPLE:
        if p["_id"] == person_id:
            p["policy"] = body.policy
            if body.name:
                p["name"] = body.name
            return p
    return _not_found(person_id)


app.include_router(people_stub)

# Role E's chat surface. The loop only ever reaches the timeline through the
# same HTTP contract as the UI — no private back door.
from backend.agent.router import router as agent_router  # noqa: E402

app.include_router(agent_router)


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
