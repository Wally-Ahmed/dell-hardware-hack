"""Edit sessions: the only path to the working timeline. Ops accumulate in a
draft, preview shows them, review applies as one undoable step."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_session_roundtrip(client):
    sid = (await client.post("/sessions")).json()["sessionId"]
    assert sid.startswith("sess_")

    ops = [
        {"op": "add_to_timeline", "assetId": "ast_dana_med", "atMs": 4200},
        {"op": "retime_clip", "clipId": "clp_2", "durationMs": 2800},
    ]
    r = (await client.post(f"/sessions/{sid}/ops", json=ops)).json()
    assert r == {"ok": True, "staleIds": []}

    preview = (await client.get(f"/sessions/{sid}/preview")).json()
    assert preview["sessionId"] == sid
    assert preview["pendingOps"] == ops
    assert preview["timeline"]["tracks"][0]["trackId"] == "trk_v1"

    review = (await client.post(f"/sessions/{sid}/review")).json()
    assert review["applied"] is True
    assert review["undoLabel"] == "Agent edit (2 ops)"


async def test_session_review_can_reject(client):
    sid = (await client.post("/sessions")).json()["sessionId"]
    await client.post(f"/sessions/{sid}/ops", json=[{"op": "swap_shot"}])

    rejected = (await client.post(f"/sessions/{sid}/review", params={"apply": "false"})).json()
    assert rejected["applied"] is False  # rejected atomically, nothing applied


async def test_unknown_session_is_not_ok(client):
    r = (await client.post("/sessions/sess_nope/ops", json=[{"op": "x"}])).json()
    assert r["ok"] is False

    review = (await client.post("/sessions/sess_nope/review")).json()
    assert review["applied"] is False
