"""The hand-written tool-calling loop (CLAUDE.md §3.2 — kept genuinely small).

One turn: user message in -> [LLM -> tool_calls -> execute -> results] until
the LLM answers in plain text, or the plan gate fires, or 8 iterations pass.

The plan gate: when the LLM proposes any plan-tier call, nothing in that
batch executes. The turn returns the plan as text plus `pendingPlan`; the
next `turn(..., approve_plan=True)` executes exactly that stored batch. The
whole batch is deferred (not just the plan-tier calls) because the chat
format requires one tool result per tool_call in an assistant message —
partial execution would corrupt the history.
"""

from __future__ import annotations

import json
from typing import Any

from .llm import LLMClient, Message
from .tools import TOOLS, ToolBelt, openai_specs

SYSTEM_PROMPT = """\
You are RushCut, the on-box video production agent for corporate marketing.
Everything runs locally on this machine; there is no cloud and nothing may
leave the building.

Consent registry: only people whose cast policy is 'approved' may appear in
any footage or generated output, foreground or background. Unknown faces are
surfaced to the human, never auto-passed. Generated output is re-checked.

Permission tiers (by reversibility and cost):
- direct tools run immediately.
- propose tools stage timeline edits in a session; the human applies them.
- plan tools (generation, ingest, upscale) run ONLY after the human approves
  your plan. When you want one, state what you will run: the model or job
  type, the reference/source ids, and a rough time estimate — then wait.

Always reference projects, assets, clips, people and jobs by their stable
ids, never by position. Be concise; this is a working session, not an essay.
"""

MAX_ITERATIONS = 8  # hard stop: a local model in a lie-loop burns demo time


class AgentLoop:
    """One conversation. History lives here; the belt holds backend state."""

    def __init__(
        self, llm: LLMClient | None = None, belt: ToolBelt | None = None
    ) -> None:
        self.llm = llm or LLMClient()
        self.belt = belt or ToolBelt()
        self.history: list[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._pending: Message | None = None  # deferred assistant msg w/ tool_calls

    async def turn(
        self, user_message: str, approve_plan: bool = False
    ) -> dict[str, Any]:
        """Run one user turn. Returns {reply, toolCalls, pendingPlan}."""
        self.history.append({"role": "user", "content": user_message})
        executed: list[dict[str, Any]] = []

        if approve_plan and self._pending is not None:
            # Approval consumes the stored plan: replay the deferred assistant
            # message into history, run its calls, then let the LLM see the
            # results and narrate. A new plan proposed later this turn defers
            # again — approval never carries forward.
            pending, self._pending = self._pending, None
            self.history.append(pending)
            await self._run_calls(pending["tool_calls"], executed)

        for _ in range(MAX_ITERATIONS):
            msg = await self.llm.chat(self.history, openai_specs())
            calls = msg.get("tool_calls") or []

            if not calls:  # plain answer — the turn is done
                self.history.append(msg)
                return self._result(msg.get("content") or "", executed)

            if any(self._tier(c) == "plan" for c in calls):
                # Plan gate: store the raw message for replay-on-approval and
                # put only a human-readable plan into history, so an
                # unapproved (or ignored) plan never leaves dangling
                # tool_calls behind.
                self._pending = msg
                summary = self._plan_summary(msg, calls)
                self.history.append({"role": "assistant", "content": summary})
                return self._result(summary, executed)

            self.history.append(msg)
            await self._run_calls(calls, executed)

        note = (
            f"Stopped after {MAX_ITERATIONS} tool rounds without a final answer. "
            "Tell me how to proceed."
        )
        self.history.append({"role": "assistant", "content": note})
        return self._result(note, executed)

    # ------------------------------------------------------------- internals

    async def _run_calls(
        self, calls: list[Message], executed: list[dict[str, Any]]
    ) -> None:
        """Execute direct/propose calls and append their results to history."""
        for call in calls:
            name = call["function"]["name"]
            args = self._args(call)
            result = await self.belt.call(name, args)
            executed.append(
                {
                    "name": name,
                    "arguments": args,
                    "tier": self._tier(call),
                    "result": result,
                }
            )
            self.history.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", name),
                    "content": json.dumps(result),
                }
            )

    def _plan_summary(self, msg: Message, calls: list[Message]) -> str:
        lines = ["PLAN — needs your approval before anything runs:"]
        if msg.get("content"):
            lines.append(str(msg["content"]).strip())
        for call in calls:
            args = json.dumps(self._args(call), sort_keys=True)
            lines.append(f"- {call['function']['name']} {args}")
        lines.append("Approve to run it, or tell me what to change.")
        return "\n".join(lines)

    def _result(self, reply: str, executed: list[dict[str, Any]]) -> dict[str, Any]:
        pending = None
        if self._pending is not None:
            pending = {
                "toolCalls": [
                    {"name": c["function"]["name"], "arguments": self._args(c)}
                    for c in self._pending["tool_calls"]
                ]
            }
        return {"reply": reply, "toolCalls": executed, "pendingPlan": pending}

    @staticmethod
    def _tier(call: Message) -> str:
        tool = TOOLS.get(call["function"]["name"])
        return (
            tool.tier if tool else "direct"
        )  # unknown -> belt returns an error result

    @staticmethod
    def _args(call: Message) -> dict[str, Any]:
        raw = call["function"].get("arguments") or "{}"
        if isinstance(raw, dict):  # some servers pre-parse arguments
            return raw
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}  # let the tool error back to the LLM as data
