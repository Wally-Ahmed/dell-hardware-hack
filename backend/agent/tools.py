"""The agent's tool belt: 18 tools, three permission tiers.

WHY the cap: tool-selection accuracy collapses as toolsets grow — measured
elsewhere at ~95% → ~71% once a large set is loaded (docs/api.md §3 pins the
hard cap at 20–30). So the belt stays flat, small, JSON-schema'd, and every
tool references objects by stable id, never ordinal position.

WHY the tiers: autonomy is gated by reversibility and cost, not by feature.
  direct  — cheap + reversible reads/annotations: the agent just does it.
  propose — timeline mutations: staged into an isolated edit session
            (POST /sessions → POST /sessions/{sid}/ops); the human applies
            them atomically via session review or rejects them. There is no
            path from here to the working timeline.
  plan    — generative / expensive jobs: the loop refuses to run these until
            the human approves a stated plan; results land in the bin as
            candidates, never in the cut.

Every handler calls the backend HTTP API and returns JSON. Errors come back
as {"error": ...} data so the LLM can self-correct instead of crashing the
loop. Env is read directly (RUSHCUT_BACKEND_URL) so the module runs
unchanged inside the NemoClaw sandbox.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

Tier = Literal["direct", "propose", "plan"]
Json = dict[str, Any]
Handler = Callable[["ToolBelt", Json], Awaitable[Json]]


@dataclass(frozen=True)
class Tool:
    name: str
    tier: Tier
    description: str
    parameters: Json  # JSON schema for the LLM
    handler: Handler


def _schema(props: Json, required: list[str] | None = None) -> Json:
    return {"type": "object", "properties": props, "required": required or []}


_ID = {"type": "string"}
_PROJECT = {"projectId": {"type": "string", "description": "Stable project id"}}


class ToolBelt:
    """Executes tools against the backend. Holds the HTTP client and the
    open edit session per project (propose-tier ops accumulate in one
    session so the human reviews them as a single atomic apply)."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        base = os.environ.get("RUSHCUT_BACKEND_URL", "http://127.0.0.1:8000")
        self._http = http or httpx.AsyncClient(base_url=base, timeout=30.0)
        self._sessions: dict[str, str] = {}  # projectId -> open sessionId

    async def call(self, name: str, arguments: Json) -> Json:
        tool = TOOLS.get(name)
        if tool is None:
            return {"error": {"code": "unknown_tool", "message": name}}
        try:
            return await tool.handler(self, arguments)
        except KeyError as exc:  # missing required argument from the LLM
            return {"error": {"code": "missing_argument", "message": str(exc)}}
        except httpx.HTTPStatusError as exc:
            return {
                "error": {
                    "code": f"http_{exc.response.status_code}",
                    "message": exc.response.text[:300],
                }
            }
        except httpx.HTTPError as exc:
            return {"error": {"code": "backend_unreachable", "message": str(exc)}}

    async def _get(self, path: str, params: Json | None = None) -> Any:
        resp = await self._http.get(path, params=params or {})
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: Any, params: Json | None = None) -> Any:
        resp = await self._http.post(path, json=body, params=params or {})
        resp.raise_for_status()
        return resp.json()

    async def _stage_op(self, project_id: str, op: str, params: Json) -> Json:
        """Propose tier: reuse (or open) the project's edit session and land
        one op there. Never touches a working timeline endpoint — the human
        applies the session atomically or rejects it (docs/api.md §3)."""
        sid = self._sessions.get(project_id)
        if sid is None:
            opened = await self._post("/sessions", None, {"projectId": project_id})
            sid = opened["sessionId"]
            self._sessions[project_id] = sid
        result = await self._post(
            f"/sessions/{sid}/ops", [{"op": op, "params": params}]
        )
        return {
            "sessionId": sid,
            "staged": True,
            "staleIds": result.get("staleIds", []),
        }

    async def _start_job(self, job_type: str, arguments: Json) -> Json:
        """Plan tier: everything slow is a job (docs/api.md §1). Returns the
        Job object; progress arrives over the websocket, result lands in the
        bin as a candidate."""
        args = dict(arguments)
        project_id = args.pop("projectId", None)
        return await self._post(
            "/jobs", {"type": job_type, "projectId": project_id, "params": args}
        )


# ---------------------------------------------------------------------------
# direct tier — cheap, reversible: just do it
# ---------------------------------------------------------------------------


async def _list_cast(belt: ToolBelt, args: Json) -> Json:
    people = await belt._get("/people", {k: v for k, v in args.items() if v})
    return {"people": people}


async def _search_memory(belt: ToolBelt, args: Json) -> Json:
    # Stub until Role D's memory layer lands; returning empty-but-honest keeps
    # the LLM from hallucinating recall.
    return {"results": [], "note": "memory search lands with Role D"}


async def _list_models(belt: ToolBelt, args: Json) -> Json:
    models = await belt._get("/models")
    task = args.get("task")
    if task:  # registry endpoint has no filter; filter here so schemas stay flat
        models = [m for m in models if m.get("task") == task]
    return {"models": models}


async def _model_status(belt: ToolBelt, args: Json) -> Json:
    return await belt._get("/models/budget")


async def _job_status(belt: ToolBelt, args: Json) -> Json:
    return await belt._get(f"/jobs/{args['jobId']}")


async def _describe_shot(belt: ToolBelt, args: Json) -> Json:
    return {
        "shotId": args.get("shotId"),
        "note": "frame description lands with Role D's contact sheets; "
        "ask the human what is in the shot for now",
    }


async def _set_marker(belt: ToolBelt, args: Json) -> Json:
    return {
        "atMs": args.get("atMs"),
        "label": args.get("label"),
        "note": "marker persistence lands with Role C's timeline; not stored yet",
    }


# ---------------------------------------------------------------------------
# propose tier — staged into an edit session, human applies atomically
# ---------------------------------------------------------------------------


async def _add_to_timeline(belt: ToolBelt, args: Json) -> Json:
    staged = await belt._stage_op(args["projectId"], "add_to_timeline", args)
    at = args.get("atMs", "playhead")
    staged["summary"] = (
        f"Staged: add asset {args['assetId']} to the timeline at {at}. "
        "Apply or reject it in the session review."
    )
    return staged


async def _retime_clip(belt: ToolBelt, args: Json) -> Json:
    staged = await belt._stage_op(args["projectId"], "retime_clip", args)
    staged["summary"] = (
        f"Staged: retime clip {args['clipId']} "
        f"(speed={args.get('speed')}, newDurationMs={args.get('newDurationMs')}). "
        "Apply or reject it in the session review."
    )
    return staged


async def _swap_shot(belt: ToolBelt, args: Json) -> Json:
    staged = await belt._stage_op(args["projectId"], "swap_shot", args)
    staged["summary"] = (
        f"Staged: swap clip {args['clipId']} to asset {args['newAssetId']}. "
        "Apply or reject it in the session review."
    )
    return staged


async def _set_cast_policy(belt: ToolBelt, args: Json) -> Json:
    body: Json = {"policy": args["policy"]}
    if args.get("name"):
        body["name"] = args["name"]
    person = await belt._post(f"/people/{args['personId']}/policy", body)
    return {
        "person": person,
        "summary": f"Consent registry: {args['personId']} -> {args['policy']}.",
    }


# ---------------------------------------------------------------------------
# plan tier — generative / expensive: runs only after an approved plan
# ---------------------------------------------------------------------------


def _job_tool(job_type: str) -> Handler:
    async def handler(belt: ToolBelt, args: Json) -> Json:
        return await belt._start_job(job_type, args)

    return handler


_REFS = {
    "references": {
        "type": "array",
        "items": _ID,
        "description": "Reference asset ids (faces, wardrobe, environment)",
    }
}

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        # ---- direct
        Tool(
            "list_cast",
            "direct",
            "List the cast registry: every detected person with consent "
            "policy (approved | unknown | remove), role, and reference crops.",
            _schema({**_PROJECT}),
            _list_cast,
        ),
        Tool(
            "search_memory",
            "direct",
            "Search project memory (notes, transcripts, prior generations).",
            _schema({"query": {"type": "string"}}, ["query"]),
            _search_memory,
        ),
        Tool(
            "list_models",
            "direct",
            "List the model registry with live state; read each model's "
            "bestFor line before choosing one. Optionally filter by task.",
            _schema(
                {"task": {"type": "string", "description": "e.g. i2v, t2v, inpaint"}}
            ),
            _list_models,
        ),
        Tool(
            "model_status",
            "direct",
            "Current model memory budget: what is resident and what fits.",
            _schema({}),
            _model_status,
        ),
        Tool(
            "job_status",
            "direct",
            "Poll one job by id: state, progress, stage, result, policy verdict.",
            _schema({"jobId": _ID}, ["jobId"]),
            _job_status,
        ),
        Tool(
            "describe_shot",
            "direct",
            "Describe what is visually in a shot by stable shot id.",
            _schema({"shotId": _ID}, ["shotId"]),
            _describe_shot,
        ),
        Tool(
            "set_marker",
            "direct",
            "Drop a labeled marker on the timeline at a time in ms.",
            _schema(
                {"atMs": {"type": "integer"}, "label": {"type": "string"}},
                ["atMs", "label"],
            ),
            _set_marker,
        ),
        # ---- propose
        Tool(
            "add_to_timeline",
            "propose",
            "Stage adding an asset to the timeline (edit session; the human "
            "applies or rejects). Never edits the working timeline directly.",
            _schema(
                {
                    **_PROJECT,
                    "assetId": _ID,
                    "trackId": _ID,
                    "atMs": {
                        "type": "integer",
                        "description": "Insert time; omit for playhead",
                    },
                },
                ["projectId", "assetId"],
            ),
            _add_to_timeline,
        ),
        Tool(
            "retime_clip",
            "propose",
            "Stage a speed/duration change for a clip (edit session; the "
            "human applies or rejects).",
            _schema(
                {
                    **_PROJECT,
                    "clipId": _ID,
                    "speed": {"type": "number", "description": "e.g. 0.5 = half speed"},
                    "newDurationMs": {"type": "integer"},
                },
                ["projectId", "clipId"],
            ),
            _retime_clip,
        ),
        Tool(
            "swap_shot",
            "propose",
            "Stage swapping a timeline clip to a different asset, e.g. a "
            "generated candidate (edit session; the human applies or rejects).",
            _schema(
                {**_PROJECT, "clipId": _ID, "newAssetId": _ID},
                ["projectId", "clipId", "newAssetId"],
            ),
            _swap_shot,
        ),
        Tool(
            "set_cast_policy",
            "propose",
            "Set a person's consent policy in the cast registry. Only "
            "'approved' people may appear in any output, even background.",
            _schema(
                {
                    "personId": _ID,
                    "policy": {
                        "type": "string",
                        "enum": ["approved", "unknown", "remove"],
                    },
                    "name": {"type": "string", "description": "Optional display name"},
                },
                ["personId", "policy"],
            ),
            _set_cast_policy,
        ),
        # ---- plan
        Tool(
            "generate_keyframe",
            "plan",
            "Generate a keyframe image from a prompt plus reference assets. "
            "Needs an approved plan; result lands in the bin as a candidate.",
            _schema(
                {**_PROJECT, "prompt": {"type": "string"}, **_REFS},
                ["projectId", "prompt"],
            ),
            _job_tool("generate_keyframe"),
        ),
        Tool(
            "generate_shot",
            "plan",
            "Generate a new video shot (keyframe -> i2v pipeline) from a "
            "prompt, an optional source asset, and reference assets. Needs an "
            "approved plan; result lands in the bin as a candidate.",
            _schema(
                {
                    **_PROJECT,
                    "prompt": {"type": "string"},
                    "sourceAssetId": {
                        **_ID,
                        "description": "Asset to derive from, if any",
                    },
                    **_REFS,
                },
                ["projectId", "prompt"],
            ),
            _job_tool("generate_shot"),
        ),
        Tool(
            "reangle_shot",
            "plan",
            "Re-render an existing shot from a new camera angle/path. Needs "
            "an approved plan.",
            _schema(
                {
                    **_PROJECT,
                    "sourceAssetId": _ID,
                    "cameraPath": {
                        "type": "string",
                        "description": "e.g. 'low-angle push-in'",
                    },
                },
                ["projectId", "sourceAssetId", "cameraPath"],
            ),
            _job_tool("reangle_shot"),
        ),
        Tool(
            "remove_person",
            "plan",
            "Inpaint a person out of a shot by person or track id. Needs an "
            "approved plan.",
            _schema(
                {**_PROJECT, "assetId": _ID, "personId": _ID, "trackId": _ID},
                ["projectId", "assetId"],
            ),
            _job_tool("remove_person"),
        ),
        Tool(
            "enforce_cast_policy",
            "plan",
            "Re-run face ID on a generated asset and remediate unapproved "
            "people (inpaint or regenerate). Needs an approved plan.",
            _schema({**_PROJECT, "assetId": _ID}, ["projectId", "assetId"]),
            _job_tool("enforce_cast_policy"),
        ),
        Tool(
            "upscale",
            "plan",
            "Upscale an approved take (SeedVR2). Expensive; needs an approved plan.",
            _schema(
                {
                    **_PROJECT,
                    "assetId": _ID,
                    "factor": {"type": "integer", "enum": [2, 4]},
                },
                ["projectId", "assetId"],
            ),
            _job_tool("upscale"),
        ),
        Tool(
            "ingest_footage",
            "plan",
            "Ingest footage from a path: scene detect, track people, build "
            "the cast registry. Slow; needs an approved plan.",
            _schema({**_PROJECT, "path": {"type": "string"}}, ["projectId", "path"]),
            _job_tool("ingest_footage"),
        ),
    ]
}


def openai_specs() -> list[Json]:
    """Tool schemas in the chat-completions `tools` format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOLS.values()
    ]


def listing() -> list[Json]:
    """Tool list with tiers, for GET /agent/tools (the AI panel renders it)."""
    return [
        {
            "name": t.name,
            "tier": t.tier,
            "description": t.description,
            "parameters": t.parameters,
        }
        for t in TOOLS.values()
    ]
