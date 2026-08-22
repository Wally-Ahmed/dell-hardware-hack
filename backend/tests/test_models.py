"""Model registry endpoints and the residency budget: LRU eviction frees room
for incoming models, and pinned models are never victims."""

import pytest

from backend.models.manager import ModelManager

pytestmark = pytest.mark.asyncio


async def test_models_endpoint_shape(client):
    models = (await client.get("/models")).json()
    assert len(models) == 20  # the whole registry, §4 shape
    for m in models:
        assert set(m) == {
            "id",
            "task",
            "tier",
            "precision",
            "approxGb",
            "loadSeconds",
            "license",
            "bestFor",
            "state",
            "pinned",
        }

    # The agent brain is resident and pinned from boot.
    brain = next(m for m in models if m["id"] == "qwen3-vl-30b-a3b")
    assert brain["state"] == "resident"
    assert brain["pinned"] is True

    budget = (await client.get("/models/budget")).json()
    assert budget["totalGb"] == 128
    assert budget["budgetGb"]["comfyui"] == 70
    assert budget["usedGb"] == 19  # just the brain so far


async def test_pin_endpoint_flips(client):
    pinned = (await client.post("/models/flux2-dev/pin", json={"pinned": True})).json()
    assert pinned["pinned"] is True
    unpinned = (await client.post("/models/flux2-dev/pin", json={"pinned": False})).json()
    assert unpinned["pinned"] is False

    missing = (await client.post("/models/nope/pin", json={"pinned": True})).json()
    assert missing["error"]["code"] == "not_found"


async def test_ensure_evicts_lru_unpinned_never_pinned():
    m = ModelManager(simulate=True)
    await m.ensure("flux2-dev")  # 32 GB, least recently used
    await m.ensure("seedvr2-3b")  # 31 GB → 63 GB resident
    await m.pin("seedvr2-3b", True)

    # 30 GB more would blow the 70 GB ComfyUI slice: the LRU unpinned
    # resident goes, the pinned one survives.
    await m.ensure("wan2.2-i2v-14b")

    states = {e["id"]: e for e in m.list()}
    assert states["flux2-dev"]["state"] == "idle"
    assert states["seedvr2-3b"]["state"] == "resident"
    assert states["wan2.2-i2v-14b"]["state"] == "resident"
    assert m.budget()["usedGb"] == 61

    # Re-ensuring a resident model is a no-op recency bump, not a reload.
    await m.ensure("seedvr2-3b")
    assert m.budget()["usedGb"] == 61


async def test_ensure_fails_when_everything_is_pinned():
    m = ModelManager(simulate=True)
    await m.ensure("flux2-dev")
    await m.ensure("seedvr2-3b")
    await m.pin("flux2-dev", True)
    await m.pin("seedvr2-3b", True)

    with pytest.raises(RuntimeError):
        await m.ensure("wan2.2-i2v-14b")  # nothing evictable, must fail loudly


async def test_people_stub_keeps_editor_alive(client):
    # Role D's seam — the stub serves the mock's three canned people so the
    # cast panel works until backend/ingest lands.
    people = (await client.get("/people")).json()
    assert len(people) == 3
    assert {p["policy"] for p in people} == {"approved", "unknown"}
