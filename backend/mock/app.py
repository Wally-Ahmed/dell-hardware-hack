"""Mock backend implementing docs/api.md.

Exists so the editor, agent, and ingest tracks can build at full speed while the
GB10 is still being provisioned. Every endpoint in the contract responds with
plausible canned data, and jobs actually walk their state machine over ~8s while
emitting real WebSocket frames.

    uvicorn backend.mock.app:app --reload --port 8000

Set MOCK_POLICY_HIT=1 to make every generate_shot come back `policy_blocked`
with an unapproved face — that is the demo beat worth rehearsing against.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

REGISTRY = Path(__file__).resolve().parents[1] / "models" / "registry.json"
POLICY_HIT = os.environ.get("MOCK_POLICY_HIT") == "1"

app = FastAPI(title="AI-native NLE (mock)", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------- state


JOBS: dict[str, dict[str, Any]] = {}
SESSIONS: dict[str, dict[str, Any]] = {}
SOCKETS: list[WebSocket] = []

PROJECT_ID = "proj_01J8W_atlas"

PEOPLE = [
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

STAGES = ["analyze", "references", "keyframe", "video", "policy_check", "finalize"]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _oid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


async def _broadcast(frame: dict[str, Any]) -> None:
    """Fan out to every connected client. Drop sockets that have gone away."""
    dead = []
    for ws in SOCKETS:
        try:
            await ws.send_json(frame)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in SOCKETS:
            SOCKETS.remove(ws)


# ---------------------------------------------------------------- jobs


class JobRequest(BaseModel):
    type: str
    projectId: str = PROJECT_ID
    params: dict[str, Any] = {}


def _new_job(req: JobRequest) -> dict[str, Any]:
    return {
        "jobId": _oid("job"),
        "projectId": req.projectId,
        "type": req.type,
        "state": "queued",
        "progress": 0.0,
        "stage": None,
        "message": "queued",
        "createdAt": _now(),
        "startedAt": None,
        "finishedAt": None,
        "result": None,
        "error": None,
        "policy": None,
    }


def _fake_asset(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "assetId": _oid("ast"),
        "projectId": job["projectId"],
        "kind": "video",
        "url": "/media/gen/mock_clip.mp4",
        "posterUrl": "/media/gen/mock_clip.jpg",
        "width": 1280,
        "height": 720,
        "fps": 24,
        "durationMs": 5000,
        "provenance": {
            "model": "wan2.2_ti2v_5B",
            "precision": "fp16",
            "prompt": job["params"].get("prompt", "low-angle push-in, lobby"),
            "negativePrompt": "additional people, crowd, bystanders",
            "seed": random.randint(1, 10**6),
            "references": ["ast_01J8T_dana_face"],
            "parentAssetId": job["params"].get("sourceAssetId"),
            "jobId": job["jobId"],
            "workflow": "wan5b_i2v",
            "policyVerdict": "blocked" if POLICY_HIT else "clear",
            "approvedBy": None,
            "approvedAt": None,
        },
    }


async def _run_job(job_id: str) -> None:
    """Walk the state machine, emitting a full Job object on every change."""
    job = JOBS[job_id]
    job.update(state="running", startedAt=_now(), message="starting")
    await _broadcast({"kind": "job", "job": job})

    for i, stage in enumerate(STAGES):
        job["stage"] = stage
        for step in range(4):
            await asyncio.sleep(0.32)
            job["progress"] = round((i * 4 + step + 1) / (len(STAGES) * 4), 3)
            job["message"] = f"{stage} — step {step + 1}/4"
            await _broadcast({"kind": "job", "job": job})
        await _broadcast(
            {"kind": "log", "jobId": job_id, "line": f"[mock] finished stage {stage}"}
        )

        if stage == "policy_check" and POLICY_HIT:
            job.update(
                state="policy_blocked",
                finishedAt=_now(),
                message="unapproved person detected in output",
                policy={
                    "verdict": "blocked",
                    "unapproved": [
                        {
                            "trackId": "trk_7",
                            "personId": None,
                            "confidence": 0.81,
                            "frames": [12, 13, 14],
                            "cropUrl": "/media/tmp/trk_7.jpg",
                        }
                    ],
                    "unresolved": [
                        {
                            "trackId": "trk_9",
                            "reason": "no usable face",
                            "cropUrl": "/media/tmp/trk_9.jpg",
                        }
                    ],
                    "remediation": "inpaint",
                    "remediatedAssetId": _oid("ast"),
                },
            )
            await _broadcast({"kind": "job", "job": job})
            return

    job.update(
        state="complete",
        progress=1.0,
        stage=None,
        finishedAt=_now(),
        message="complete",
        result=_fake_asset(job),
        policy={
            "verdict": "clear",
            "unapproved": [],
            "unresolved": [],
            "remediation": None,
            "remediatedAssetId": None,
        },
    )
    await _broadcast({"kind": "job", "job": job})


@app.post("/jobs")
async def create_job(req: JobRequest) -> dict[str, Any]:
    job = _new_job(req)
    job["params"] = req.params
    JOBS[job["jobId"]] = job
    asyncio.create_task(_run_job(job["jobId"]))
    return job


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    return JOBS.get(job_id, {"error": {"code": "not_found", "message": job_id}})


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job and job["state"] in ("queued", "running"):
        job.update(state="cancelled", finishedAt=_now(), message="cancelled by user")
        await _broadcast({"kind": "job", "job": job})
    return job or {"error": {"code": "not_found", "message": job_id}}


@app.get("/jobs")
async def list_jobs(projectId: str | None = None, state: str | None = None) -> list[dict[str, Any]]:
    out = list(JOBS.values())
    if projectId:
        out = [j for j in out if j["projectId"] == projectId]
    if state:
        out = [j for j in out if j["state"] == state]
    return out


# ---------------------------------------------------------------- models


@app.get("/models")
async def list_models() -> list[dict[str, Any]]:
    """Registry plus live state. Same source feeds the agent and the Models panel."""
    data = json.loads(REGISTRY.read_text())
    resident = {"qwen3-vl-30b-a3b", "flux2-klein-4b", "sam2.1-hiera-large"}
    out = []
    for m in data["models"]:
        out.append(
            {
                **{
                    k: m[k]
                    for k in (
                        "id",
                        "task",
                        "tier",
                        "precision",
                        "approxGb",
                        "loadSeconds",
                        "license",
                        "bestFor",
                    )
                },
                "state": "resident" if m["id"] in resident else "idle",
                "pinned": m["id"] == "qwen3-vl-30b-a3b",
            }
        )
    return out


@app.get("/models/budget")
async def model_budget() -> dict[str, Any]:
    data = json.loads(REGISTRY.read_text())
    return {"budgetGb": data["budgetGb"], "totalGb": 128, "usedGb": 34.4}


# ---------------------------------------------------------------- cast


@app.get("/people")
async def list_people(projectId: str = PROJECT_ID) -> list[dict[str, Any]]:
    return [p for p in PEOPLE if p["projectId"] == projectId]


class PolicyUpdate(BaseModel):
    policy: str  # approved | unknown | remove
    name: str | None = None


@app.post("/people/{person_id}/policy")
async def set_policy(person_id: str, body: PolicyUpdate) -> dict[str, Any]:
    for p in PEOPLE:
        if p["_id"] == person_id:
            p["policy"] = body.policy
            if body.name:
                p["name"] = body.name
            return p
    return {"error": {"code": "not_found", "message": person_id}}


# ---------------------------------------------------------------- edit sessions


@app.post("/sessions")
async def open_session(projectId: str = PROJECT_ID) -> dict[str, Any]:
    sid = _oid("sess")
    SESSIONS[sid] = {"sessionId": sid, "projectId": projectId, "ops": [], "applied": False}
    return {"sessionId": sid}


@app.post("/sessions/{sid}/ops")
async def session_ops(sid: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
    s = SESSIONS.get(sid)
    if not s:
        return {"ok": False, "staleIds": [], "error": "no such session"}
    s["ops"].extend(ops)
    return {"ok": True, "staleIds": []}


@app.get("/sessions/{sid}/preview")
async def session_preview(sid: str) -> dict[str, Any]:
    s = SESSIONS.get(sid, {})
    return {
        "sessionId": sid,
        "timeline": {
            "tracks": [
                {
                    "trackId": "trk_v1",
                    "kind": "video",
                    "clips": [
                        {"clipId": "clp_1", "assetId": "ast_lobby_wide", "startMs": 0, "durationMs": 4200},
                        {"clipId": "clp_2", "assetId": "ast_dana_med", "startMs": 4200, "durationMs": 3100},
                    ],
                }
            ]
        },
        "pendingOps": s.get("ops", []),
    }


@app.post("/sessions/{sid}/review")
async def session_review(sid: str, apply: bool = True) -> dict[str, Any]:
    s = SESSIONS.get(sid)
    if not s:
        return {"applied": False, "error": "no such session"}
    s["applied"] = apply
    return {"applied": apply, "undoLabel": f"Agent edit ({len(s['ops'])} ops)"}


# ---------------------------------------------------------------- websocket


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    SOCKETS.append(websocket)
    try:
        await websocket.send_json({"kind": "models", "models": await list_models()})
        while True:
            await websocket.receive_text()  # keepalive; client sends nothing meaningful
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in SOCKETS:
            SOCKETS.remove(websocket)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mock": True,
        "policyHitMode": POLICY_HIT,
        "note": "Canned data. Real backend lands on the `backend` branch.",
    }
