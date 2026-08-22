"""Deterministic stand-in brain for off-box development and rehearsal.

The Codespace has no GPU and no Ollama, but the demo loop (chat -> plan ->
approve -> job -> policy check) must be drivable end to end before anyone
stands in front of judges. This serves just enough of the OpenAI-compatible
chat-completions surface for AgentLoop, with scripted decisions instead of a
model. It is NOT the product brain: the GB10 points RUSHCUT_OLLAMA_URL at real
Ollama and this file never runs there.

    python -m uvicorn backend.agent.dev_brain:app --port 11434

AgentLoop's default RUSHCUT_OLLAMA_URL (http://127.0.0.1:11434/v1) then works
unchanged.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="rushcut dev brain (scripted, not a model)")


class ChatRequest(BaseModel):
    model: str = "dev-brain"
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    max_tokens: int | None = None


def _tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Scripted routing. Keyword-matched on the last USER message; after tool
    results arrive we summarize instead of calling more tools, which is what
    terminates AgentLoop's iteration."""
    last = messages[-1]
    if last.get("role") == "tool":
        try:
            payload = json.loads(last.get("content") or "{}")
        except (TypeError, ValueError):
            payload = {}
        job_id = payload.get("jobId")
        tail = f" Job {job_id} is queued — watch it on the timeline." if job_id else ""
        return {"role": "assistant", "content": f"Done.{tail}"}

    text = str(last.get("content", "")).lower()
    if any(w in text for w in ("shot", "generate", "angle", "scene of")):
        return {
            "role": "assistant",
            "content": "Plan: draft keyframe from Dana's references, then Wan 5B "
            "image-to-video at 720p. Estimated ~90s on the box.",
            "tool_calls": [
                _tool_call(
                    "generate_shot",
                    {"prompt": str(last.get("content", ""))[:300], "references": ["per_dana"]},
                )
            ],
        }
    if any(w in text for w in ("cast", "people", "who is")):
        return {"role": "assistant", "content": None, "tool_calls": [_tool_call("list_cast", {})]}
    if "model" in text:
        return {"role": "assistant", "content": None, "tool_calls": [_tool_call("list_models", {})]}
    return {
        "role": "assistant",
        "content": "Dev brain (scripted). Try: 'low-angle shot of Dana in the lobby', "
        "'who is in the cast?', or 'what models are loaded?'.",
    }


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest) -> dict[str, Any]:
    message = _decide(req.messages)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "model": req.model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": "dev-brain", "object": "model"}]}
