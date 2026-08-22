"""HTTP surface for renders. NOT mounted here — Role B owns backend/app.py
and adds `app.include_router(render_router)` (see backend/render/README.md).

In-memory registry only: render records die with the process, which is the
right lifetime for a demo box — the .mp4 files themselves survive under
settings.media_dir/renders/.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.config import settings
from backend.core.ws import hub

from .ffmpeg import render

router = APIRouter(tags=["render"])

_registry: dict[str, dict[str, Any]] = {}
# asyncio only keeps weak refs to tasks; without this dict a render task
# could be garbage-collected mid-encode.
_tasks: dict[str, asyncio.Task[None]] = {}


def _not_found(ref: str) -> dict[str, Any]:
    # House convention (backend/app.py): JSON error bodies, never bare 404s,
    # so panels render one shape.
    return {"error": {"code": "not_found", "message": ref}}


class RenderRequest(BaseModel):
    projectId: str
    timeline: dict[str, Any]
    filename: str | None = None


@router.post("/render")
async def start_render(req: RenderRequest) -> dict[str, Any]:
    render_id = f"rnd_{uuid.uuid4().hex[:12]}"
    # Path(...).name strips any directory parts so a hostile filename
    # cannot escape the renders dir.
    name = Path(req.filename).name if req.filename else f"{render_id}.mp4"
    out_path = Path(settings.media_dir) / "renders" / name
    _registry[render_id] = {
        "renderId": render_id,
        "projectId": req.projectId,
        "state": "rendering",
        "progress": 0.0,
    }
    _tasks[render_id] = asyncio.create_task(_run(render_id, req.timeline, out_path))
    return {"renderId": render_id}


@router.get("/render/{render_id}")
async def render_status(render_id: str) -> dict[str, Any]:
    """{state: rendering|complete|failed, progress, path?} — poll fallback
    for when the websocket drops (same contract as /jobs/{id})."""
    return _registry.get(render_id) or _not_found(render_id)


async def _run(render_id: str, timeline: dict[str, Any], out_path: Path) -> None:
    entry = _registry[render_id]
    last_decile = -1

    async def on_progress(fraction: float) -> None:
        nonlocal last_decile
        entry["progress"] = round(fraction, 4)
        decile = int(fraction * 10)
        if decile > last_decile:
            # Broadcast only at 10% steps so the ws log feed stays readable
            # next to the generation jobs sharing it.
            last_decile = decile
            await hub.log(render_id, f"render {int(fraction * 100)}%")

    await hub.log(render_id, f"render started -> {out_path.name}")
    result = await render(timeline, out_path, on_progress=on_progress)
    if result["ok"]:
        entry.update(
            state="complete",
            progress=1.0,
            path=result["path"],
            durationMs=result["durationMs"],
        )
        await hub.log(render_id, f"render complete ({result['durationMs']} ms)")
    else:
        # Last stderr line is the actual ffmpeg error; the fuller tail is
        # kept on the registry entry for GET /render/{id}.
        tail_lines = result["stderr_tail"].splitlines()
        reason = tail_lines[-1] if tail_lines else "unknown error"
        entry.update(state="failed", error=result["stderr_tail"][-2000:])
        await hub.log(render_id, f"render failed: {reason}")
    _tasks.pop(render_id, None)
