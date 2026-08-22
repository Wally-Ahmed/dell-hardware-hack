"""Router contract test with a stubbed render() — verifies the registry
lifecycle and response shapes without needing ffmpeg installed."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import FastAPI

import backend.render.router as render_router_module


def test_render_lifecycle(tmp_path: Path, monkeypatch) -> None:
    rendered: dict[str, Any] = {}

    async def fake_render(timeline, out_path, on_progress=None) -> dict[str, Any]:
        rendered["out_path"] = Path(out_path)
        if on_progress is not None:
            await on_progress(0.55)  # router's callback is async
        return {
            "path": str(out_path),
            "durationMs": 2500,
            "ok": True,
            "stderr_tail": "",
        }

    monkeypatch.setattr(render_router_module, "render", fake_render)
    # settings is a frozen dataclass, so swap the router's module binding
    # instead of mutating it.
    monkeypatch.setattr(
        render_router_module, "settings", SimpleNamespace(media_dir=tmp_path)
    )

    app = FastAPI()
    app.include_router(render_router_module.router)

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            body = {"projectId": "proj_x", "timeline": {"tracks": []}}
            render_id = (await c.post("/render", json=body)).json()["renderId"]
            assert render_id.startswith("rnd_")

            # The background task shares this loop; a few yields let it finish.
            for _ in range(50):
                status = (await c.get(f"/render/{render_id}")).json()
                if status["state"] != "rendering":
                    break
                await asyncio.sleep(0.01)

            assert status["state"] == "complete"
            assert status["progress"] == 1.0
            assert status["path"] == str(rendered["out_path"])
            assert rendered["out_path"].parent == tmp_path / "renders"

            missing = (await c.get("/render/rnd_nope")).json()
            assert missing["error"]["code"] == "not_found"

    asyncio.run(scenario())
