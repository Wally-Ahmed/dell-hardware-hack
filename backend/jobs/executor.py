"""Pluggable job executors. The queue calls `run(job, emit)` and never learns
whether frames came from a timer loop or a real ComfyUI — flipping
RUSHCUT_EXECUTOR is the only difference between the Codespace and the GB10.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import typing
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from backend.core.config import settings
from backend.core.ws import hub
from backend.jobs.state import STAGES, now_iso, oid

# Called after every job mutation so the hub broadcasts full objects, never
# deltas (docs/api.md §1).
Emit = Callable[[dict[str, Any]], Awaitable[None]]

TICKS_PER_STAGE = 4


class Executor(Protocol):
    async def run(self, job: dict[str, Any], emit: Emit) -> dict[str, Any]:
        """Walk `job` to a terminal state, awaiting `emit(job)` after every
        mutation. Returns the same (mutated) job dict."""
        ...


def _policy_blocked() -> dict[str, Any]:
    # Byte-for-byte the mock's payload so the frontend's policy card needs
    # zero changes when the real detector lands: one unapproved track and one
    # unresolved "no usable face" track, remediated by inpainting.
    return {
        "verdict": "blocked",
        "unapproved": [
            {
                "trackId": "trk_7",
                "personId": None,
                "confidence": 0.81,
                "frames": [12, 13, 14],
                "cropUrl": "/media/tmp/trk_7.jpg",
            }
        ],
        "unresolved": [
            {
                "trackId": "trk_9",
                "reason": "no usable face",
                "cropUrl": "/media/tmp/trk_9.jpg",
            }
        ],
        "remediation": "inpaint",
        "remediatedAssetId": oid("ast"),
    }


def _policy_clear() -> dict[str, Any]:
    return {
        "verdict": "clear",
        "unapproved": [],
        "unresolved": [],
        "remediation": None,
        "remediatedAssetId": None,
    }


def _fake_asset(job: dict[str, Any]) -> dict[str, Any]:
    """The mock's asset shape with full provenance (docs/api.md §2)."""
    return {
        "assetId": oid("ast"),
        "projectId": job["projectId"],
        "kind": "video",
        "url": "/media/gen/mock_clip.mp4",
        "posterUrl": "/media/gen/mock_clip.jpg",
        "width": 1280,
        "height": 720,
        "fps": 24,
        "durationMs": 5000,
        "provenance": {
            "model": "wan2.2_ti2v_5B",
            "precision": "fp16",
            "prompt": job["params"].get("prompt", "low-angle push-in, lobby"),
            "negativePrompt": "additional people, crowd, bystanders",
            "seed": random.randint(1, 10**6),
            "references": ["ast_01J8T_dana_face"],
            "parentAssetId": job["params"].get("sourceAssetId"),
            "jobId": job["jobId"],
            "workflow": "wan5b_i2v",
            "policyVerdict": "clear",
            "approvedBy": None,
            "approvedAt": None,
        },
    }


class SimulatedExecutor:
    """Walks the whole state machine on a timer, frame-compatible with the
    verified mock so the frontend cannot tell the difference.

    `seconds` overrides settings.sim_job_seconds — Settings freezes at import,
    and tests need 0.5s in one file and 5s in another.
    """

    def __init__(self, seconds: float | None = None) -> None:
        self._seconds = seconds

    async def run(self, job: dict[str, Any], emit: Emit) -> dict[str, Any]:
        seconds = self._seconds if self._seconds is not None else settings.sim_job_seconds
        total_ticks = len(STAGES) * TICKS_PER_STAGE
        # forcePolicyHit lets a single demo click rehearse the consent beat;
        # RUSHCUT_POLICY_HIT=1 flips every job, mirroring the mock's env knob.
        policy_hit = (
            bool(job["params"].get("forcePolicyHit"))
            or os.environ.get("RUSHCUT_POLICY_HIT") == "1"
        )

        job.update(state="running", startedAt=now_iso(), message="starting")
        await emit(job)

        for i, stage in enumerate(STAGES):
            job["stage"] = stage
            for step in range(TICKS_PER_STAGE):
                await asyncio.sleep(seconds / total_ticks)
                if job["state"] == "cancelled":
                    # The queue flipped state mid-tick; stop touching the job.
                    return job
                job["progress"] = round((i * TICKS_PER_STAGE + step + 1) / total_ticks, 3)
                job["message"] = f"{stage} — step {step + 1}/{TICKS_PER_STAGE}"
                await emit(job)
            await hub.log(job["jobId"], f"[sim] finished stage {stage}")

            if stage == "policy_check" and policy_hit:
                job.update(
                    state="policy_blocked",
                    finishedAt=now_iso(),
                    message="unapproved person detected in output",
                    policy=_policy_blocked(),
                )
                await emit(job)
                return job

        job.update(
            state="complete",
            progress=1.0,
            stage=None,
            finishedAt=now_iso(),
            message="complete",
            result=_fake_asset(job),
            policy=_policy_clear(),
        )
        await emit(job)
        return job


def patch_workflow(template: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Fill an API-format ComfyUI workflow by node-title convention.

    Workflow authors title the nodes they want parameterized (the `_meta.title`
    field in API-format JSON):

      - "RUSHCUT_PROMPT": `inputs.text`  ← params["prompt"]
      - "RUSHCUT_SEED":   `inputs.seed`  ← params["seed"]
      - "RUSHCUT_IMAGE":  `inputs.image` ← params["imageRef"]
                          (falls back to the first of params["references"])

    Every other title is left untouched, so templates stay freely editable in
    the ComfyUI graph editor without breaking the contract, and a missing
    param keeps the template's baked-in default. Returns a deep copy — the
    loaded template is reusable across jobs.
    """
    workflow = copy.deepcopy(template)
    image = params.get("imageRef") or next(iter(params.get("references") or []), None)
    fills: dict[str, tuple[str, Any]] = {
        "RUSHCUT_PROMPT": ("text", params.get("prompt")),
        "RUSHCUT_SEED": ("seed", params.get("seed")),
        "RUSHCUT_IMAGE": ("image", image),
    }
    for node in workflow.values():
        if not isinstance(node, dict):
            continue  # top-level "$comment" strings and friends
        title = node.get("_meta", {}).get("title")
        if title in fills:
            key, value = fills[title]
            if value is not None:
                node.setdefault("inputs", {})[key] = value
    return workflow


class ComfyExecutor:
    """Drives a real ComfyUI over HTTP — the GB10 path.

    Flow: load `{settings.workflows_dir}/{template}.json`, patch it via the
    RUSHCUT node-title convention (see patch_workflow), POST {base}/prompt,
    poll {base}/history/{prompt_id} every 2s mapping progress into the `video`
    stage, then pull outputs through {base}/view into settings.media_dir.

    Cancellation: the queue flips job["state"] to "cancelled"; we notice
    between polls and POST {base}/interrupt so the GPU stops burning too.
    """

    # Job type -> workflow template. One executor serves every job type, so
    # the template must be resolved per job, not fixed at construction — the
    # ctor default only covers unlisted types. File names match
    # workflows/README.md; a missing file fails the job with a pointer there.
    TEMPLATE_BY_TYPE: typing.ClassVar[dict[str, str]] = {
        "generate_shot": "wan5b_i2v",
        "generate_keyframe": "klein_keyframe_multiref",
        "remove_person": "vace_inpaint_person",
        "enforce_cast_policy": "vace_inpaint_person",
        "replace_person": "animate_replace",
        "reangle_shot": "fun_camera_reangle",
        "upscale": "seedvr2_upscale",
        "interpolate": "rife_interp",
    }

    def __init__(self, base_url: str | None = None, template: str = "wan5b_i2v") -> None:
        self._base = (base_url or settings.comfy_url).rstrip("/")
        self._template = template

    def _template_for(self, job: dict[str, Any]) -> str:
        return self.TEMPLATE_BY_TYPE.get(job["type"], self._template)

    def _registry_model(self, template: str) -> dict[str, Any] | None:
        # Provenance should name the model, not the workflow file; the
        # registry is the single source of that mapping.
        data = json.loads(settings.registry_path.read_text())
        for model in data["models"]:
            if model.get("workflowTemplate") == template:
                return model
        return None

    async def run(self, job: dict[str, Any], emit: Emit) -> dict[str, Any]:
        self._template = self._template_for(job)
        template_path = settings.workflows_dir / f"{self._template}.json"
        if not template_path.exists():
            job.update(
                state="failed",
                finishedAt=now_iso(),
                message=f"no workflow template for '{job['type']}'",
                error={
                    "code": "template_missing",
                    "message": f"{template_path.name} not found in workflows/ — "
                    "build and save it per workflows/README.md, then retry",
                },
            )
            await emit(job)
            return job
        template = json.loads(template_path.read_text())
        # Seed before patching so the workflow and the provenance agree.
        params = dict(job["params"])
        params.setdefault("seed", random.randint(1, 10**6))
        workflow = patch_workflow(template, params)

        job.update(
            state="running",
            startedAt=now_iso(),
            stage="video",
            message=f"submitting {self._template} to ComfyUI",
        )
        await emit(job)

        async with httpx.AsyncClient(base_url=self._base, timeout=30.0) as client:
            resp = await client.post("/prompt", json={"prompt": workflow})
            resp.raise_for_status()
            prompt_id = resp.json()["prompt_id"]
            await hub.log(job["jobId"], f"comfy prompt {prompt_id} queued")

            video_band = STAGES.index("video") / len(STAGES)
            polls = 0
            while True:
                await asyncio.sleep(2.0)
                if job["state"] == "cancelled":
                    await client.post("/interrupt")
                    return job
                history = (await client.get(f"/history/{prompt_id}")).json()
                entry = history.get(prompt_id)
                if entry and entry.get("outputs"):
                    break
                polls += 1
                # History exposes no step counter, so creep through the
                # `video` band rather than lying with a full bar.
                job["progress"] = round(
                    min(video_band + polls * 0.01, video_band + 1 / len(STAGES)), 3
                )
                job["message"] = f"ComfyUI rendering ({polls * 2}s)"
                await emit(job)

            asset = await self._collect(client, job, entry, params)

        job.update(
            state="complete",
            progress=1.0,
            stage=None,
            finishedAt=now_iso(),
            message="complete",
            result=asset,
            policy=_policy_clear(),
        )
        await emit(job)
        return job

    async def _collect(
        self,
        client: httpx.AsyncClient,
        job: dict[str, Any],
        entry: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        settings.media_dir.mkdir(parents=True, exist_ok=True)
        for output in entry["outputs"].values():
            for key, kind in (("videos", "video"), ("gifs", "video"), ("images", "image")):
                for item in output.get(key, []):
                    resp = await client.get(
                        "/view",
                        params={
                            "filename": item["filename"],
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output"),
                        },
                    )
                    resp.raise_for_status()
                    (settings.media_dir / item["filename"]).write_bytes(resp.content)
                    return self._asset(job, params, item["filename"], kind)
        raise RuntimeError("ComfyUI reported success but returned no outputs")

    def _asset(
        self, job: dict[str, Any], params: dict[str, Any], filename: str, kind: str
    ) -> dict[str, Any]:
        model = self._registry_model(self._template)
        return {
            "assetId": oid("ast"),
            "projectId": job["projectId"],
            "kind": kind,
            "url": f"/media/{filename}",
            "posterUrl": None,
            "width": 1280,
            "height": 720,
            "fps": 24,
            "durationMs": 5000,
            "provenance": {
                "model": model["id"] if model else self._template,
                "precision": model["precision"] if model else None,
                "prompt": params.get("prompt"),
                "negativePrompt": params.get("negativePrompt"),
                "seed": params["seed"],
                "references": params.get("references") or [],
                "parentAssetId": params.get("sourceAssetId"),
                "jobId": job["jobId"],
                "workflow": self._template,
                "policyVerdict": "clear",
                "approvedBy": None,
                "approvedAt": None,
            },
        }


def get_executor() -> Executor:
    if settings.executor == "comfy":
        return ComfyExecutor(settings.comfy_url)
    return SimulatedExecutor()
