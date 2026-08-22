"""forcePolicyHit ends the job `policy_blocked` at the policy_check stage with
the mock's exact payload — the consent registry doing its job, not a failure."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_force_policy_hit_blocks(client, wait_terminal):
    r = await client.post(
        "/jobs",
        json={
            "type": "generate_shot",
            "projectId": "proj_test",
            "params": {"prompt": "lobby crowd", "forcePolicyHit": True},
        },
    )
    job_id = r.json()["jobId"]

    final, _ = await wait_terminal(client, job_id)

    assert final["state"] == "policy_blocked"
    assert final["stage"] == "policy_check"
    assert final["result"] is None  # blocked output never becomes an asset

    policy = final["policy"]
    assert policy["verdict"] == "blocked"
    assert len(policy["unapproved"]) == 1
    assert policy["unapproved"][0]["confidence"] == 0.81
    assert policy["unapproved"][0]["personId"] is None
    assert len(policy["unresolved"]) == 1
    assert policy["unresolved"][0]["reason"] == "no usable face"
    assert policy["remediation"] == "inpaint"
    assert policy["remediatedAssetId"].startswith("ast_")
