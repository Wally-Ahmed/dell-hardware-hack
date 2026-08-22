"""OpenAI-compatible chat-completions client for the local brain (Ollama).

Deliberately thin: the loop needs exactly one capability — messages + tool
schemas in, one assistant message (possibly carrying `tool_calls`) out.
No streaming, no retries, no provider abstraction: the model is box-local,
the demo is tonight, and every knob we do not add is debugging time we keep.

Env is read directly here (not via backend.core.config) so the module stays
importable standalone inside the NemoClaw sandbox, where only this package
and httpx exist.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

Message = dict[str, Any]


class LLMClient:
    """Minimal async client for Ollama's OpenAI-compatible `/v1` endpoint."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = os.environ.get(
            "RUSHCUT_OLLAMA_URL", "http://127.0.0.1:11434/v1"
        ).rstrip("/")
        self.model = os.environ.get("RUSHCUT_BRAIN", "qwen3-vl:30b")
        # A cold qwen3-vl:30b load takes tens of seconds before the first
        # token; a short default timeout would report model loading as errors.
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=10.0)
        )

    async def chat(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> Message:
        """One non-streaming completion. Returns the assistant message dict."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        resp = await self._http.post(f"{self.base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]
