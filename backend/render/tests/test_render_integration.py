"""End-to-end render with a real ffmpeg. Skips gracefully when ffmpeg is not
installed (CI/Codespace without media tools) — a skip is a pass here.

asyncio.run() inside sync tests keeps the suite independent of any
pytest-asyncio mode configuration.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from backend.render.ffmpeg import ffprobe_duration_ms, render

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def _make_clip(path: Path, color: str) -> None:
    """1s lavfi color clip — tiny frame size keeps the test fast."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=320x240:r=24:d=1",
            "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
        timeout=60,
    )


def _timeline(clips: list[dict[str, Any]]) -> dict[str, Any]:
    return {"tracks": [{"trackId": "trk_v1", "kind": "video", "clips": clips}]}


def test_render_two_clips_with_gap(tmp_path: Path) -> None:
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _make_clip(a, "red")
    _make_clip(b, "blue")

    timeline = _timeline(
        [
            {
                "clipId": "clp_a",
                "assetId": "ast_a",
                "startMs": 0,
                "durationMs": 1000,
                "assetPath": str(a),
            },
            {
                # 500 ms gap before this clip -> black filler.
                "clipId": "clp_b",
                "assetId": "ast_b",
                "startMs": 1500,
                "durationMs": 1000,
                "assetPath": str(b),
            },
        ]
    )

    out = tmp_path / "out.mp4"
    progress: list[float] = []
    result = asyncio.run(render(timeline, out, on_progress=progress.append))

    assert result["ok"], result["stderr_tail"]
    assert out.exists() and out.stat().st_size > 0

    duration = ffprobe_duration_ms(out)
    assert duration is not None
    # 1000 + 500 gap + 1000; container rounding gets a generous window.
    assert abs(duration - 2500) <= 150, f"duration {duration} ms"
    assert abs(result["durationMs"] - 2500) <= 150

    # Progress climbed monotonically into [0, 1] and finished at 100%.
    assert progress, "on_progress never called"
    assert progress == sorted(progress)
    assert all(0.0 <= p <= 1.0 for p in progress)
    assert progress[-1] == 1.0


def test_render_failure_returns_ok_false(tmp_path: Path) -> None:
    # Missing source file: ffmpeg exits non-zero; render must report, not raise.
    timeline = _timeline(
        [
            {
                "clipId": "clp_x",
                "assetId": "ast_x",
                "startMs": 0,
                "durationMs": 1000,
                "assetPath": str(tmp_path / "does_not_exist.mp4"),
            }
        ]
    )
    result = asyncio.run(render(timeline, tmp_path / "out.mp4"))
    assert result["ok"] is False
    assert result["stderr_tail"]
