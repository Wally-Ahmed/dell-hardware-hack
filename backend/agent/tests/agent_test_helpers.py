"""Test doubles: a scripted LLM and a recording fake backend.

Named distinctively (not conftest, not test_*) so it can never collide with
Role B's backend/tests/ modules when someone runs the whole tree at once.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

Message = dict[str, Any]


class FakeLLM:
    """Returns the next scripted assistant message on every chat() call."""

    def __init__(self, script: list[Message]) -> None:
        self.script = list(script)
        self.calls = 0

    async def chat(
        self, messages: list[Message], tools: list[dict] | None = None
    ) -> Message:
        self.calls += 1
        assert self.script, (
            "FakeLLM script exhausted — test asked for more turns than scripted"
        )
        return self.script.pop(0)


def tool_call(name: str, args: dict[str, Any], call_id: str = "call_1") -> Message:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def assistant_calls(*calls: Message) -> Message:
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def assistant_text(text: str) -> Message:
    return {"role": "assistant", "content": text}


class RecordingBackend:
    """Canned responses for every endpoint the tool belt touches, plus a
    (method, path) log so tests can assert what was — and was not — called."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.requests.append((method, path))
        if (method, path) == ("GET", "/people"):
            return httpx.Response(
                200, json=[{"_id": "per_dana", "name": "Dana", "policy": "approved"}]
            )
        if (method, path) == ("GET", "/models"):
            return httpx.Response(200, json=[{"id": "wan2.2_ti2v_5B", "task": "t2v"}])
        if (method, path) == ("GET", "/models/budget"):
            return httpx.Response(200, json={"usedGb": 12.0, "capGb": 70.0})
        if method == "GET" and path.startswith("/jobs/"):
            return httpx.Response(
                200, json={"jobId": path.rsplit("/", 1)[1], "state": "running"}
            )
        if (method, path) == ("POST", "/jobs"):
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jobId": "job_test1",
                    "state": "queued",
                    "type": body["type"],
                    "params": body["params"],
                },
            )
        if (method, path) == ("POST", "/sessions"):
            return httpx.Response(200, json={"sessionId": "sess_test1"})
        if method == "POST" and path.startswith("/sessions/") and path.endswith("/ops"):
            return httpx.Response(200, json={"ok": True, "staleIds": []})
        if (
            method == "POST"
            and path.startswith("/people/")
            and path.endswith("/policy")
        ):
            person_id = path.split("/")[2]
            policy = json.loads(request.content)["policy"]
            return httpx.Response(200, json={"_id": person_id, "policy": policy})
        return httpx.Response(
            404, json={"error": f"unhandled in test backend: {method} {path}"}
        )
