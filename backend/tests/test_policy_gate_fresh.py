"""The gate must work on the very first request of a process — the store
seeds on list(), and get()-only access saw an empty registry (live-caught)."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_gate_first_call_on_fresh_store(client):
    resp = await client.post(
        "/jobs",
        json={"type": "generate_shot", "params": {"references": ["per_dana"]}},
    )
    assert resp.json()["state"] == "queued"
