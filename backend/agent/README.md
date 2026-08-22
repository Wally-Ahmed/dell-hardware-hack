# backend/agent — the tool-calling agent (Role E)

**Role B: mount with one line in `backend/app.py`:**

```python
from backend.agent.router import router as agent_router  # then:

app.include_router(agent_router)
```

That exposes `POST /agent/chat` `{message, approvePlan?}` and `GET /agent/tools`.

| File | What |
|---|---|
| `llm.py` | OpenAI-compatible client for Ollama (`RUSHCUT_OLLAMA_URL`, `RUSHCUT_BRAIN`) |
| `tools.py` | 18 tools in three tiers (direct / propose / plan) calling `RUSHCUT_BACKEND_URL` |
| `loop.py` | The ~150-line loop with the plan-approval gate (`AgentLoop.turn`) |
| `router.py` | FastAPI router (chat + tool listing) |
| `tests/` | No-network pytest suite: `python -m pytest backend/agent/tests/ -x -q` |

Sandbox config for the GB10 lives in `nemoclaw/` at the repo root.
