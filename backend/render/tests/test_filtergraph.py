"""build_filtergraph unit tests. Assertions are on substrings, not the whole
graph string — exact ffmpeg syntax is brittle and not the contract; the
integration test proves the graph actually runs."""

from __future__ import annotations

from typing import Any

import pytest

from backend.render.ffmpeg import (
    build_filtergraph,
    timeline_duration_ms,
)


def _clip(
    cid: str,
    path: str,
    start_ms: int,
    dur_ms: int,
    in_ms: int | None = None,
) -> dict[str, Any]:
    clip: dict[str, Any] = {
        "clipId": cid,
        "assetId": f"ast_{cid}",
        "startMs": start_ms,
        "durationMs": dur_ms,
        "assetPath": path,
    }
    if in_ms is not None:
        clip["inMs"] = in_ms
    return clip


def _timeline(clips: list[dict[str, Any]]) -> dict[str, Any]:
    return {"tracks": [{"trackId": "trk_v1", "kind": "video", "clips": clips}]}


def test_two_clips_and_gap() -> None:
    timeline = _timeline(
        [
            _clip("a", "/fake/a.mp4", 0, 1000),
            _clip("b", "/fake/b.mp4", 1500, 1000),  # 500 ms hole before it
        ]
    )
    inputs, fc, maps = build_filtergraph(timeline)

    assert inputs == ["-i", "/fake/a.mp4", "-i", "/fake/b.mp4"]
    assert maps == ["-map", "[vout]"]
    # 2 clips + 1 black gap segment feed the concat.
    assert "concat=n=3:v=1:a=0" in fc
    assert "color=c=black" in fc
    assert "d=0.500" in fc
    # Each clip trims from its own source and rebases timestamps.
    assert "[0:v]trim=start=0.000:end=1.000" in fc
    assert "[1:v]trim=start=0.000:end=1.000" in fc
    assert "setpts=PTS-STARTPTS" in fc


def test_in_ms_honored() -> None:
    timeline = _timeline([_clip("a", "/fake/a.mp4", 0, 1000, in_ms=250)])
    _, fc, _ = build_filtergraph(timeline)
    assert "trim=start=0.250:end=1.250" in fc


def test_contiguous_clips_have_no_gap() -> None:
    timeline = _timeline(
        [
            _clip("a", "/fake/a.mp4", 0, 1000),
            _clip("b", "/fake/b.mp4", 1000, 1000),
        ]
    )
    _, fc, _ = build_filtergraph(timeline)
    assert "concat=n=2:v=1:a=0" in fc
    assert "color" not in fc


def test_leading_gap_becomes_black() -> None:
    timeline = _timeline([_clip("a", "/fake/a.mp4", 500, 1000)])
    _, fc, _ = build_filtergraph(timeline)
    assert "concat=n=2:v=1:a=0" in fc
    # The black segment precedes the clip chain in the graph.
    assert fc.index("color=c=black") < fc.index("[0:v]")


def test_normalization_and_overrides() -> None:
    timeline = _timeline([_clip("a", "/fake/a.mp4", 0, 1000)])
    _, fc, _ = build_filtergraph(timeline)
    assert "scale=1280:720" in fc
    assert "fps=24" in fc
    assert "format=yuv420p" in fc

    _, fc_small, _ = build_filtergraph(timeline, fps=30, width=640, height=360)
    assert "scale=640:360" in fc_small
    assert "fps=30" in fc_small


def test_preview_envelope_accepted() -> None:
    # Callers may pipe the whole GET /sessions/{sid}/preview body in.
    envelope = {
        "sessionId": "ses_1",
        "timeline": _timeline([_clip("a", "/fake/a.mp4", 0, 1000)]),
        "pendingOps": [],
    }
    inputs, fc, _ = build_filtergraph(envelope)
    assert inputs == ["-i", "/fake/a.mp4"]
    assert "concat=n=1:v=1:a=0" in fc
    assert timeline_duration_ms(envelope) == 1000


def test_duration_spans_gaps() -> None:
    timeline = _timeline(
        [
            _clip("a", "/fake/a.mp4", 0, 1000),
            _clip("b", "/fake/b.mp4", 1500, 1000),
        ]
    )
    assert timeline_duration_ms(timeline) == 2500


def test_empty_timeline_raises() -> None:
    with pytest.raises(ValueError, match="no video clips"):
        build_filtergraph({"tracks": []})


def test_missing_asset_path_raises() -> None:
    clip = _clip("a", "", 0, 1000)
    del clip["assetPath"]
    with pytest.raises(ValueError, match="assetPath"):
        build_filtergraph(_timeline([clip]))
