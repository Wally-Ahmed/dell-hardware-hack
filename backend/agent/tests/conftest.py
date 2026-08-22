"""Shared fixtures. No network anywhere: the LLM is scripted (FakeLLM) and
the backend is an httpx.MockTransport that records every request."""

from __future__ import annotations

import sys
from pathlib import Path

# Make `backend.agent.*` importable no matter where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import httpx
import pytest
import pytest_asyncio
from agent_test_helpers import RecordingBackend

from backend.agent.tools import ToolBelt


@pytest.fixture
def backend() -> RecordingBackend:
    return RecordingBackend()


@pytest_asyncio.fixture
async def belt(backend: RecordingBackend):
    http = httpx.AsyncClient(
        transport=backend.transport(), base_url="http://testserver"
    )
    yield ToolBelt(http=http)
    await http.aclose()
