"""WebSocket hub. One envelope, three kinds: job | log | models.

Full objects on every change, never deltas — reconciling partial state across
three people's code at 16:00 is not a fight worth having (docs/api.md §1).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class Hub:
    def __init__(self) -> None:
        self._sockets: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._sockets.append(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._sockets:
                self._sockets.remove(ws)

    async def broadcast(self, frame: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        async with self._lock:
            sockets = list(self._sockets)
        for ws in sockets:
            try:
                await ws.send_json(frame)
            except Exception:  # noqa: BLE001 — any send failure means prune
                dead.append(ws)
        for ws in dead:
            await self.remove(ws)

    async def job(self, job: dict[str, Any]) -> None:
        await self.broadcast({"kind": "job", "job": job})

    async def log(self, job_id: str, line: str) -> None:
        await self.broadcast({"kind": "log", "jobId": job_id, "line": line})

    async def models(self, models: list[dict[str, Any]]) -> None:
        await self.broadcast({"kind": "models", "models": models})


hub = Hub()
