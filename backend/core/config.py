"""Runtime configuration. Everything comes from the environment with sane
defaults for the Codespace; the GB10 overrides via scripts/setup_box.sh.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    # "simulated" (Codespace, no GPU) | "comfy" (GB10, real ComfyUI)
    executor: str = os.environ.get("RUSHCUT_EXECUTOR", "simulated")
    comfy_url: str = os.environ.get("RUSHCUT_COMFY_URL", "http://127.0.0.1:8188")
    mongo_uri: str = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/rushcut")
    registry_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get("RUSHCUT_REGISTRY", BACKEND_DIR / "models" / "registry.json")
        )
    )
    workflows_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("RUSHCUT_WORKFLOWS", BACKEND_DIR.parent / "workflows")
        )
    )
    media_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("RUSHCUT_MEDIA", "/tmp/rushcut-media"))
    )
    # Simulated jobs walk the whole state machine in ~this many seconds.
    sim_job_seconds: float = float(os.environ.get("RUSHCUT_SIM_SECONDS", "8"))


settings = Settings()
