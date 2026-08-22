"""Tool belt: propose tier only ever touches /sessions, and the registry
stays capped and tiered."""

from __future__ import annotations

import pytest
from agent_test_helpers import FakeLLM, assistant_calls, assistant_text, tool_call

from backend.agent.loop import AgentLoop
from backend.agent.tools import TOOLS, listing, openai_specs


@pytest.mark.asyncio
async def test_propose_tier_stages_into_session_never_timeline(belt, backend) -> None:
    llm = FakeLLM(
        [
            assistant_calls(
                tool_call(
                    "add_to_timeline",
                    {"projectId": "proj_1", "assetId": "ast_1", "atMs": 0},
                    call_id="call_a",
                ),
                tool_call(
                    "swap_shot",
                    {"projectId": "proj_1", "clipId": "clip_1", "newAssetId": "ast_2"},
                    call_id="call_b",
                ),
            ),
            assistant_text("Staged both for your review."),
        ]
    )
    out = await AgentLoop(llm=llm, belt=belt).turn("cut it together")

    # One session opened, reused for the second op — one atomic human review.
    assert backend.requests.count(("POST", "/sessions")) == 1
    assert backend.requests.count(("POST", "/sessions/sess_test1/ops")) == 2
    # Every mutation went through /sessions; no timeline endpoint exists to hit.
    posts = [path for method, path in backend.requests if method == "POST"]
    assert posts and all(path.startswith("/sessions") for path in posts)
    assert not any("timeline" in path for _, path in backend.requests)

    result = out["toolCalls"][0]["result"]
    assert result["sessionId"] == "sess_test1"
    assert result["staged"] is True
    assert result["staleIds"] == []
    assert "session review" in result["summary"]


@pytest.mark.asyncio
async def test_set_cast_policy_posts_to_registry(belt, backend) -> None:
    llm = FakeLLM(
        [
            assistant_calls(
                tool_call(
                    "set_cast_policy", {"personId": "per_unknown_1", "policy": "remove"}
                )
            ),
            assistant_text("Marked for removal."),
        ]
    )
    out = await AgentLoop(llm=llm, belt=belt).turn("remove the unknown person")

    assert ("POST", "/people/per_unknown_1/policy") in backend.requests
    assert out["toolCalls"][0]["result"]["person"]["policy"] == "remove"


def test_registry_is_capped_and_tiered() -> None:
    # docs/api.md §3: hard cap 20-30 because selection accuracy collapses past it.
    assert len(TOOLS) == 18
    assert {t.tier for t in TOOLS.values()} == {"direct", "propose", "plan"}
    assert {t.name for t in TOOLS.values() if t.tier == "plan"} == {
        "generate_keyframe",
        "generate_shot",
        "reangle_shot",
        "remove_person",
        "enforce_cast_policy",
        "upscale",
        "ingest_footage",
    }
    for spec in openai_specs():
        assert spec["type"] == "function"
        assert spec["function"]["parameters"]["type"] == "object"
    assert all(
        {"name", "tier", "description", "parameters"} <= set(e) for e in listing()
    )
