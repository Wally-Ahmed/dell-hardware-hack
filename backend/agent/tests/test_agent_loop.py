"""Loop behavior: direct tools run at once, plan tools gate on approval,
and the loop always terminates."""

from __future__ import annotations

import pytest
from agent_test_helpers import FakeLLM, assistant_calls, assistant_text, tool_call

from backend.agent.loop import MAX_ITERATIONS, AgentLoop


@pytest.mark.asyncio
async def test_direct_tool_executes_immediately(belt, backend) -> None:
    llm = FakeLLM(
        [
            assistant_calls(tool_call("list_cast", {"projectId": "proj_1"})),
            assistant_text("Two approved, one unknown."),
        ]
    )
    out = await AgentLoop(llm=llm, belt=belt).turn("who is in the cast?")

    assert out["reply"] == "Two approved, one unknown."
    assert out["pendingPlan"] is None
    assert [c["name"] for c in out["toolCalls"]] == ["list_cast"]
    assert out["toolCalls"][0]["result"]["people"][0]["_id"] == "per_dana"
    assert ("GET", "/people") in backend.requests


@pytest.mark.asyncio
async def test_plan_tool_gates_until_approved(belt, backend) -> None:
    args = {
        "projectId": "proj_1",
        "prompt": "low-angle Dana in the lobby",
        "references": ["ast_1"],
    }
    llm = FakeLLM(
        [
            assistant_calls(tool_call("generate_shot", args)),
            assistant_text("Queued as job_test1."),
        ]
    )
    loop = AgentLoop(llm=llm, belt=belt)

    first = await loop.turn("make me a new lobby shot")
    assert first["pendingPlan"] is not None
    assert first["pendingPlan"]["toolCalls"][0]["name"] == "generate_shot"
    assert first["pendingPlan"]["toolCalls"][0]["arguments"]["prompt"] == args["prompt"]
    assert first["toolCalls"] == []  # nothing executed on first ask
    assert ("POST", "/jobs") not in backend.requests
    assert "PLAN" in first["reply"]

    second = await loop.turn("yes, run it", approve_plan=True)
    assert second["pendingPlan"] is None
    assert second["reply"] == "Queued as job_test1."
    assert [c["name"] for c in second["toolCalls"]] == ["generate_shot"]
    assert second["toolCalls"][0]["result"]["jobId"] == "job_test1"
    assert backend.requests.count(("POST", "/jobs")) == 1


@pytest.mark.asyncio
async def test_unapproved_plan_stays_pending_and_never_runs(belt, backend) -> None:
    llm = FakeLLM(
        [
            assistant_calls(
                tool_call("upscale", {"projectId": "proj_1", "assetId": "ast_1"})
            ),
            assistant_text("Holding off, then."),
        ]
    )
    loop = AgentLoop(llm=llm, belt=belt)

    await loop.turn("upscale that take")
    second = await loop.turn("hmm, wait")  # no approve_plan — plan must not run

    assert ("POST", "/jobs") not in backend.requests
    assert second["pendingPlan"] is not None  # still offered, still gated
    assert second["toolCalls"] == []


@pytest.mark.asyncio
async def test_loop_terminates_at_max_iterations(belt, backend) -> None:
    llm = FakeLLM(
        [
            assistant_calls(tool_call("list_cast", {}, call_id=f"call_{i}"))
            for i in range(MAX_ITERATIONS + 4)
        ]
    )
    out = await AgentLoop(llm=llm, belt=belt).turn("loop forever")

    assert llm.calls == MAX_ITERATIONS  # hard stop, script not exhausted
    assert len(out["toolCalls"]) == MAX_ITERATIONS
    assert f"Stopped after {MAX_ITERATIONS} tool rounds" in out["reply"]
    assert out["pendingPlan"] is None
