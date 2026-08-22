"""Pre-GPU cast gate: jobs referencing non-approved people are born
policy_blocked and never reach the executor. Idea adapted from a peer
project's review; the post-generation output check stays authoritative."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_unapproved_ref_blocks_before_gpu(client):
    resp = await client.post(
        "/jobs",
        json={
            "type": "generate_shot",
            "params": {"prompt": "x", "references": ["per_unknown_1"]},
        },
    )
    job = resp.json()
    assert job["state"] == "policy_blocked"
    assert job["stage"] == "policy_check"
    assert job["policy"]["verdict"] == "blocked"
    assert job["policy"]["unapproved"][0]["personId"] == "per_unknown_1"
    # It never ran: progress untouched, and it stays blocked.
    await asyncio.sleep(0.8)
    again = (await client.get(f"/jobs/{job['jobId']}")).json()
    assert again["state"] == "policy_blocked"


@pytest.mark.asyncio
async def test_missing_person_is_unresolved_and_blocked(client):
    resp = await client.post(
        "/jobs",
        json={"type": "generate_shot", "params": {"references": ["per_ghost"]}},
    )
    job = resp.json()
    assert job["state"] == "policy_blocked"
    assert job["policy"]["unresolved"][0]["trackId"] == "per_ghost"
    assert job["policy"]["unresolved"][0]["reason"] == "not in cast registry"


@pytest.mark.asyncio
async def test_approved_refs_pass_and_asset_refs_ignored(client):
    resp = await client.post(
        "/jobs",
        json={
            "type": "generate_shot",
            "params": {"prompt": "x", "references": ["per_dana", "ast_01J8T_x"]},
        },
    )
    job = resp.json()
    assert job["state"] == "queued"
    # walks to completion like any other job
    for _ in range(40):
        await asyncio.sleep(0.1)
        job = (await client.get(f"/jobs/{job['jobId']}")).json()
        if job["state"] == "complete":
            break
    assert job["state"] == "complete"
    assert job["policy"]["verdict"] == "clear"
