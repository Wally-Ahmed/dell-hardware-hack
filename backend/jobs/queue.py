"""In-memory job queue, concurrency 1 on purpose — the GB10 runs one
generative job at a time, so the worker loop *is* the GPU lock. Mongo
persistence is a stretch goal we deliberately skipped; jobs die with the
process and the poll endpoint exists for socket drops, not restarts.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from backend.core.ws import hub
from backend.jobs.executor import Emit, Executor
from backend.jobs.state import new_job, now_iso


class JobQueue:
    def __init__(self, executor: Executor, emit: Emit | None = None) -> None:
        self._executor = executor
        # hub.job by default; tests inject a recorder.
        self._emit: Emit = emit if emit is not None else hub.job
        self._jobs: dict[str, dict[str, Any]] = {}
        self._pending: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    def start(self) -> None:
        # Called from the app lifespan (or a test) so the worker lands on the
        # running loop, not whichever loop happened to import us.
        self._worker = asyncio.create_task(self._drain())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def submit(
        self, type: str, project_id: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        job = new_job(type, project_id, params)
        self._jobs[job["jobId"]] = job
        await self._emit(job)
        await self._pending.put(job["jobId"])
        return job

    async def cancel(self, job_id: str) -> dict[str, Any] | None:
        """Best-effort. The state flip *is* the cancel flag: SimulatedExecutor
        checks it between ticks and stops mutating; ComfyExecutor checks it
        between history polls and POSTs {base}/interrupt to free the GPU."""
        job = self._jobs.get(job_id)
        if job and job["state"] in ("queued", "running"):
            job.update(state="cancelled", finishedAt=now_iso(), message="cancelled by user")
            await self._emit(job)
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)

    def list(
        self, project_id: str | None = None, state: str | None = None
    ) -> list[dict[str, Any]]:
        out = list(self._jobs.values())
        if project_id:
            out = [j for j in out if j["projectId"] == project_id]
        if state:
            out = [j for j in out if j["state"] == state]
        return out

    async def _drain(self) -> None:
        while True:
            job_id = await self._pending.get()
            job = self._jobs[job_id]
            if job["state"] != "queued":
                continue  # cancelled while waiting its turn
            try:
                await self._executor.run(job, self._emit)
            except Exception as exc:  # noqa: BLE001 — an executor bug must not kill the worker
                job.update(
                    state="failed",
                    finishedAt=now_iso(),
                    message="job failed",
                    error={"code": "executor_error", "message": str(exc)},
                )
                await self._emit(job)
