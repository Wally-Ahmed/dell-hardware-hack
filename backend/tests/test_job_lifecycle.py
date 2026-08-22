"""A submitted job walks queued → running → complete and lands with full
provenance — the seam every panel and the agent build against."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_job_walks_to_complete(client, wait_terminal):
    r = await client.post(
        "/jobs",
        json={
            "type": "generate_shot",
            "projectId": "proj_test",
            "params": {"prompt": "low-angle push-in, Dana crossing the lobby"},
        },
    )
    submitted = r.json()
    assert submitted["state"] == "queued"
    assert submitted["progress"] == 0.0
    assert submitted["jobId"].startswith("job_")

    final, seen = await wait_terminal(client, submitted["jobId"])

    # The 0.5s sim (conftest pins RUSHCUT_SIM_SECONDS) plus 20ms polling
    # guarantees we observe the running state, not just the endpoints.
    assert final["state"] == "complete"
    assert "running" in seen
    assert final["progress"] == 1.0
    assert final["startedAt"] is not None
    assert final["finishedAt"] is not None

    prov = final["result"]["provenance"]
    assert prov["model"] == "wan2.2_ti2v_5B"
    assert isinstance(prov["seed"], int)
    assert prov["jobId"] == submitted["jobId"]
    assert prov["prompt"] == "low-angle push-in, Dana crossing the lobby"
    assert final["policy"]["verdict"] == "clear"


async def test_job_listing_filters(client, wait_terminal):
    a = (await client.post("/jobs", json={"type": "generate_shot", "projectId": "proj_a"})).json()
    b = (await client.post("/jobs", json={"type": "render", "projectId": "proj_b"})).json()
    await wait_terminal(client, a["jobId"])
    await wait_terminal(client, b["jobId"])

    ours = (await client.get("/jobs", params={"projectId": "proj_a"})).json()
    assert [j["jobId"] for j in ours] == [a["jobId"]]
    done = (await client.get("/jobs", params={"state": "complete"})).json()
    assert {j["jobId"] for j in done} == {a["jobId"], b["jobId"]}
