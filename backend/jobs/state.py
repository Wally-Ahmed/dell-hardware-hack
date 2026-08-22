"""Job state machine as data. Executors walk STAGES, the queue owns the
transitions, and everyone — editor, agent, tests — agrees on the shape by
importing this instead of guessing (docs/api.md §1).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

# Order matters: progress is tick_index / total_ticks across these in order,
# and the consent gate fires between `policy_check` and `finalize`.
STAGES = ["analyze", "references", "keyframe", "video", "policy_check", "finalize"]

# queued → running → complete | failed | cancelled | policy_blocked
# `policy_blocked` is not a failure — it is the consent registry doing its job.
STATES = ("queued", "running", "complete", "failed", "cancelled", "policy_blocked")
TERMINAL_STATES = ("complete", "failed", "cancelled", "policy_blocked")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def oid(prefix: str) -> str:
    # Stable and opaque — clients render ids, never parse them.
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def new_job(type: str, project_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Job object exactly as the contract draws it, plus `params` — the mock
    carries params on the job too, and executors read prompt/seed/refs from
    there rather than through a side channel."""
    return {
        "jobId": oid("job"),
        "projectId": project_id,
        "type": type,
        "state": "queued",
        "progress": 0.0,
        "stage": None,
        "message": "queued",
        "createdAt": now_iso(),
        "startedAt": None,
        "finishedAt": None,
        "result": None,
        "error": None,
        "policy": None,
        "params": params,
    }
