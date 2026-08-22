"""Shared fixtures. No network, no GPU, no Mongo — everything runs in-process
against the ASGI app.
"""

import asyncio
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

# Settings is a frozen dataclass read once at import, so the env must be
# pinned before *any* backend module loads. conftest executes before the test
# modules import backend.*, which makes this the one reliable place — and the
# backend imports in the fixtures below stay lazy for the same reason.
os.environ["RUSHCUT_SIM_SECONDS"] = "0.5"
os.environ["RUSHCUT_EXECUTOR"] = "simulated"
os.environ.pop("RUSHCUT_POLICY_HIT", None)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app import app

    # httpx's ASGITransport never runs lifespan, so we drive it ourselves —
    # each test gets a fresh queue, model manager, and session store.
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
def wait_terminal():
    """Poll a job until it leaves the running states, returning the final job
    plus every state observed along the way."""
    from backend.jobs.state import TERMINAL_STATES

    async def _wait(
        client: httpx.AsyncClient, job_id: str, timeout: float = 10.0
    ) -> tuple[dict[str, Any], list[str]]:
        seen: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = (await client.get(f"/jobs/{job_id}")).json()
            seen.append(job["state"])
            if job["state"] in TERMINAL_STATES:
                return job, seen
            await asyncio.sleep(0.02)
        raise AssertionError(f"job {job_id} never went terminal; saw {seen}")

    return _wait
