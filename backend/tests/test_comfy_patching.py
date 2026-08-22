"""ComfyExecutor's template patching, exercised without any ComfyUI: nodes
titled RUSHCUT_* get their inputs filled, everything else stays untouched."""

import copy
import json
from pathlib import Path

from backend.jobs.executor import (
    ComfyExecutor,
    SimulatedExecutor,
    get_executor,
    patch_workflow,
)

FIXTURE = Path(__file__).parent / "fixtures" / "wan_fixture.json"


def test_patch_fills_titled_nodes():
    template = json.loads(FIXTURE.read_text())
    before = copy.deepcopy(template)

    patched = patch_workflow(
        template,
        {
            "prompt": "Dana crossing the lobby",
            "seed": 881203,
            "imageRef": "/media/refs/dana_face.jpg",
        },
    )

    assert patched["1"]["inputs"]["text"] == "Dana crossing the lobby"
    assert patched["1"]["inputs"]["clip"] == ["5", 0]  # sibling inputs survive
    assert patched["2"]["inputs"]["seed"] == 881203
    assert patched["2"]["inputs"]["steps"] == 4
    assert patched["3"]["inputs"]["image"] == "/media/refs/dana_face.jpg"

    # Unknown titles (and the $comment string) are untouched, and the template
    # itself is never mutated — it gets reused across jobs.
    assert patched["4"] == before["4"]
    assert patched["$comment"] == before["$comment"]
    assert template == before


def test_patch_missing_params_keep_defaults():
    template = json.loads(FIXTURE.read_text())
    patched = patch_workflow(template, {})
    assert patched == template  # baked-in defaults stand when params are absent


def test_patch_image_falls_back_to_references():
    template = json.loads(FIXTURE.read_text())
    patched = patch_workflow(template, {"references": ["ast_dana_face.png", "ast_b.png"]})
    assert patched["3"]["inputs"]["image"] == "ast_dana_face.png"


def test_get_executor_honors_settings():
    # conftest pins RUSHCUT_EXECUTOR=simulated; ComfyExecutor still has to
    # construct cleanly since the GB10 flips one env var to use it.
    assert isinstance(get_executor(), SimulatedExecutor)
    assert ComfyExecutor("http://127.0.0.1:8188", "wan5b_i2v") is not None
