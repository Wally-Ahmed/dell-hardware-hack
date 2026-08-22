"""Timeline JSON -> ffmpeg filtergraph -> H.264 file.

Consumes the shape served by GET /sessions/{sid}/preview:

    {"tracks": [{"trackId", "kind": "video",
                 "clips": [{"clipId", "assetId", "startMs", "durationMs"}]}]}

extended minimally per clip with:
    assetPath  absolute file path — tonight the renderer resolves it directly
               (assetId -> path resolution through the media store is a TODO
               wired by the conductor later)
    inMs       source in-point, default 0

Audio is deliberately ignored tonight: the demo clips are MOS (generated
video carries no audio stream), and concatenating a mix of silent and
soundful inputs fails unless every segment is padded with anullsrc. Adding
audio later is a straight extension — atrim/anullsrc per segment and a=1 on
the concat — not a redesign.

All subprocess invocations pass argument lists (never a shell string), so
timeline-supplied paths cannot inject commands.
"""

from __future__ import annotations

import asyncio
import inspect
import subprocess
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_FPS = 24
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720

# How many trailing stderr lines to keep for post-mortems. ffmpeg's real
# error is always in the last handful of lines; the full log is noise.
_STDERR_TAIL_LINES = 40


def _video_clips(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    """Clips of the first video track, sorted by startMs.

    Accepts either the bare {"tracks": [...]} shape or the whole preview
    envelope {"sessionId", "timeline": {...}} so callers can pipe the
    /sessions/{sid}/preview response straight in.
    """
    if "tracks" not in timeline and isinstance(timeline.get("timeline"), dict):
        timeline = timeline["timeline"]
    for track in timeline.get("tracks", []):
        if track.get("kind") == "video":
            # Zero/negative-length clips would produce empty trim segments
            # and break the concat count, so they are dropped here.
            clips = [
                c for c in track.get("clips", []) if int(c.get("durationMs", 0)) > 0
            ]
            return sorted(clips, key=lambda c: int(c.get("startMs", 0)))
    return []


def timeline_duration_ms(timeline: dict[str, Any]) -> int:
    """End of the last clip == total output duration (gaps included)."""
    return max(
        (
            int(c.get("startMs", 0)) + int(c["durationMs"])
            for c in _video_clips(timeline)
        ),
        default=0,
    )


def build_filtergraph(
    timeline: dict[str, Any],
    fps: int = DEFAULT_FPS,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> tuple[list[str], str, list[str]]:
    """Return (inputs, filter_complex, maps) for the first video track.

    Each clip becomes trim -> setpts -> scale/pad -> fps; gaps between
    clips become black `color` segments so startMs offsets are honored;
    everything is concatenated in timeline order.

    Raises ValueError on an unrenderable timeline (no clips / no assetPath) —
    render() converts that into an ok=False result instead of raising.
    """
    clips = _video_clips(timeline)
    if not clips:
        raise ValueError("timeline has no video clips to render")

    # concat refuses inputs that differ in size, rate, pixel format, or SAR,
    # and heterogeneous sources are the norm here (generated clips, phone
    # footage, lavfi color) — so every segment funnels through the same
    # normalization before it reaches the concat.
    normalize = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={fps},format=yuv420p,setsar=1"
    )

    inputs: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    cursor_ms = 0
    for i, clip in enumerate(clips):
        path = clip.get("assetPath")
        if not path:
            raise ValueError(
                f"clip {clip.get('clipId')!r} has no assetPath "
                "(tonight the caller resolves assetId -> path; see module doc)"
            )
        start_ms = int(clip.get("startMs", 0))
        dur_ms = int(clip["durationMs"])
        in_ms = int(clip.get("inMs", 0))

        gap_ms = start_ms - cursor_ms
        if gap_ms > 0:
            # Holes in the timeline render as black rather than collapsing —
            # the export must match what the NLE preview shows.
            chains.append(
                f"color=c=black:s={width}x{height}:r={fps}:d={gap_ms / 1000:.3f},"
                f"format=yuv420p,setsar=1[g{i}]"
            )
            labels.append(f"[g{i}]")
        # gap_ms <= 0 means overlap: clips butt-join in startMs order.
        # Resolving overlaps is the editor's job, not the renderer's.

        # Gaps are lavfi sources inside the graph and add no -i inputs,
        # so clip i is always ffmpeg input stream i.
        inputs += ["-i", str(path)]
        chains.append(
            # trim keeps source timestamps, so setpts rebases each segment
            # to t=0 — without it concat stalls waiting for the gap in PTS.
            f"[{i}:v]trim=start={in_ms / 1000:.3f}:end={(in_ms + dur_ms) / 1000:.3f},"
            f"setpts=PTS-STARTPTS,{normalize}[c{i}]"
        )
        labels.append(f"[c{i}]")
        cursor_ms = max(cursor_ms, start_ms + dur_ms)

    chains.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[vout]")
    return inputs, ";".join(chains), ["-map", "[vout]"]


def ffprobe_duration_ms(path: str | Path) -> int | None:
    """Container duration in ms, or None if ffprobe is missing/unhappy."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return int(float(out.stdout.strip()) * 1000)
    except ValueError:
        return None


async def _call_progress(cb: Callable[[float], Any], value: float) -> None:
    # The router hands us an async callback (it broadcasts over the ws hub);
    # tests hand us a plain list.append. Support both.
    result = cb(value)
    if inspect.isawaitable(result):
        await result


async def render(
    timeline: dict[str, Any],
    out_path: str | Path,
    on_progress: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    """Render the timeline to out_path with libx264/yuv420p.

    Never raises on failure — a broken timeline, missing ffmpeg, or a
    non-zero exit all come back as ok=False with the stderr tail, because
    the caller is a fire-and-forget job task with nobody above it to catch.
    """
    out_path = Path(out_path)
    total_ms = timeline_duration_ms(timeline)

    def failure(reason: str) -> dict[str, Any]:
        return {
            "path": str(out_path),
            "durationMs": 0,
            "ok": False,
            "stderr_tail": reason,
        }

    try:
        inputs, graph, maps = build_filtergraph(timeline)
    except ValueError as exc:
        return failure(str(exc))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-nostats",  # stats go to -progress instead of \r-spam on stderr
        *inputs,
        "-filter_complex", graph,
        *maps,
        "-c:v", "libx264",
        "-preset", "veryfast",  # demo tonight: encode speed over a few % bitrate
        "-pix_fmt", "yuv420p",  # browser/QuickTime-safe output
        "-movflags", "+faststart",  # moov up front so <video> starts instantly
        "-progress", "pipe:1",  # machine-readable frame= lines on stdout
        str(out_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return failure(f"ffmpeg not runnable: {exc}")

    total_frames = max(1, round(total_ms / 1000 * DEFAULT_FPS))
    tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)

    async def read_progress() -> None:
        assert proc.stdout is not None
        while line_bytes := await proc.stdout.readline():
            line = line_bytes.decode(errors="replace").strip()
            if not line.startswith("frame=") or on_progress is None:
                continue
            try:
                frame = int(line.split("=", 1)[1].strip())
            except ValueError:
                continue
            await _call_progress(on_progress, min(frame / total_frames, 1.0))

    async def read_stderr() -> None:
        assert proc.stderr is not None
        while line_bytes := await proc.stderr.readline():
            tail.append(line_bytes.decode(errors="replace").rstrip())

    # Both pipes must be drained concurrently or ffmpeg deadlocks on a
    # full stderr buffer while we block on stdout.
    await asyncio.gather(read_progress(), read_stderr())
    returncode = await proc.wait()

    ok = returncode == 0 and out_path.exists()
    if ok and on_progress is not None:
        # ffmpeg's last report can land a frame short of the computed
        # total; force the bar to 100% on confirmed success.
        await _call_progress(on_progress, 1.0)

    duration_ms = await asyncio.to_thread(ffprobe_duration_ms, out_path) if ok else None
    return {
        "path": str(out_path),
        "durationMs": duration_ms
        if duration_ms is not None
        else (total_ms if ok else 0),
        "ok": ok,
        "stderr_tail": "\n".join(tail),
    }
