"""Cancellation: the queue flips state, the executor notices between ticks and
stops mutating. Slow 5s sim so nothing races the assertions."""

import asyncio

import pytest

from backend.jobs.executor import SimulatedExecutor
from backend.jobs.queue import JobQueue

pytestmark = pytest.mark.asyncio


async def test_cancel_running_job():
    frames: list[str] = []

    async def record(job: dict) -> None:
        frames.append(job["state"])

    # 5s sim → first tick lands at ~208ms, leaving a wide window to cancel
    # mid-run without any timing luck involved.
    queue = JobQueue(SimulatedExecutor(seconds=5), emit=record)
    queue.start()
    try:
        job = await queue.submit("generate_shot", "proj_test", {})
        await asyncio.sleep(0.05)  # let the worker pick it up
        assert queue.get(job["jobId"])["state"] == "running"

        await queue.cancel(job["jobId"])
        cancelled = queue.get(job["jobId"])
        assert cancelled["state"] == "cancelled"
        assert cancelled["message"] == "cancelled by user"
        assert cancelled["finishedAt"] is not None

        # Two ticks later the executor must have stopped touching the job.
        await asyncio.sleep(0.5)
        assert queue.get(job["jobId"])["state"] == "cancelled"
        assert frames[-1] == "cancelled"
    finally:
        await queue.stop()


async def test_cancel_queued_job_never_runs():
    async def emit(job: dict) -> None:
        pass

    queue = JobQueue(SimulatedExecutor(seconds=5), emit=emit)
    # Worker not started: the job stays queued, like one parked behind a long
    # render on the single-GPU queue.
    job = await queue.submit("generate_shot", "proj_test", {})
    await queue.cancel(job["jobId"])
    assert queue.get(job["jobId"])["state"] == "cancelled"

    queue.start()
    try:
        await asyncio.sleep(0.05)
        # The worker skips jobs that were cancelled while waiting their turn.
        assert queue.get(job["jobId"])["state"] == "cancelled"
    finally:
        await queue.stop()


async def test_cancel_endpoint(client):
    job = (await client.post("/jobs", json={"type": "generate_shot"})).json()
    r = (await client.post(f"/jobs/{job['jobId']}/cancel")).json()
    assert r["state"] == "cancelled"

    await asyncio.sleep(0.6)  # longer than the whole 0.5s sim
    still = (await client.get(f"/jobs/{job['jobId']}")).json()
    assert still["state"] == "cancelled"

    missing = (await client.post("/jobs/job_nope/cancel")).json()
    assert missing["error"]["code"] == "not_found"
