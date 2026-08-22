"""HTTP surface for the agent. NOT mounted here — Role B owns app.py and
adds `app.include_router(agent_router)` (see backend/agent/README.md).

One module-level loop = one shared conversation. That is deliberate for the
demo: one operator, one box, and the AI panel needs the agent to remember
the last few exchanges across requests.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from .loop import AgentLoop
from .tools import listing

router = APIRouter(tags=["agent"])

_loop: AgentLoop | None = None


def get_loop() -> AgentLoop:
    # Lazy so importing the router never demands a reachable Ollama.
    global _loop
    if _loop is None:
        _loop = AgentLoop()
    return _loop


class ChatIn(BaseModel):
    message: str
    approvePlan: bool = False


@router.post("/agent/chat")
async def chat(body: ChatIn) -> dict[str, Any]:
    """One agent turn -> {reply, toolCalls, pendingPlan}."""
    return await get_loop().turn(body.message, approve_plan=body.approvePlan)


@router.get("/agent/tools")
async def tools() -> list[dict[str, Any]]:
    """The tool belt with tiers, for the AI panel to render."""
    return listing()
