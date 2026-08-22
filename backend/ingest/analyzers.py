"""Analyzer seams for the ingest pipeline.

The ANALYSIS MODELS (PySceneDetect, SAM2, InsightFace, SigLIP2) only exist on
the GB10, so the pipeline depends on these Protocols instead of libraries.
Three families implement them:

- Real adapters: lazy-import stubs that raise a clear "runs on the GB10"
  message off-box. They are finished on the box (grep TODO(box)).
- FixedIntervalDetector: a working zero-dependency scene fallback.
- Fakes: fed from fixture data, they make the whole pipeline testable and
  demoable on a laptop with no CV stack at all.

Selection: RUSHCUT_ANALYZERS=real|fake (default fake off-box) via
`choose_analyzers()`, which probes availability and falls back rather than
letting the demo die on an ImportError.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Protocol

from backend.db.store import DANA_FACE, MARCUS_FACE

BBox = tuple[float, float, float, float]  # x, y, w, h — normalized 0..1
Vector = list[float]


@dataclass
class Shot:
    index: int
    startMs: int
    endMs: int


@dataclass
class Track:
    """One person, continuously tracked within a shot."""

    trackId: str
    shotIndex: int
    frames: list[int]
    bboxes: list[BBox]
    # Placeholder until the box's crop stage writes real jpgs.
    cropPaths: list[str] = field(default_factory=list)
    # Per-frame {sharpness, frontality, brightness} in 0..1, produced by the
    # tracker stage (it already holds the decoded frames). Optional because
    # off-box fakes may not care; refs.py treats missing frames as neutral.
    frameQuality: dict[int, dict[str, float]] | None = None


# ---------------------------------------------------------------- protocols


class SceneDetector(Protocol):
    def detect(self, path: str) -> list[Shot]: ...


class PersonTracker(Protocol):
    def track(self, path: str, shots: list[Shot]) -> list[Track]: ...


class FaceEmbedder(Protocol):
    def embed(self, track: Track) -> list[Vector] | None:
        """Face vectors for a track, None when no usable face was found."""
        ...


class BodyEmbedder(Protocol):
    def embed(self, track: Track) -> list[Vector]: ...


@dataclass
class Analyzers:
    """The bundle the pipeline consumes — swap one seam without touching the rest."""

    detector: SceneDetector
    tracker: PersonTracker
    face: FaceEmbedder
    body: BodyEmbedder


# ---------------------------------------------------------------- real adapters
# Thin on purpose: imports happen inside the call so this module always loads
# off-box, and every failure message says exactly where the real thing lives.


class PySceneDetectDetector:
    """Content-aware shot boundaries via PySceneDetect."""

    def __init__(self, threshold: float = 27.0) -> None:
        self.threshold = threshold

    def detect(self, path: str) -> list[Shot]:
        try:
            from scenedetect import ContentDetector, detect  # lazy: GB10-only dep
        except ImportError as exc:
            raise RuntimeError(
                "scenedetect runs on the GB10 — install from the wheelhouse"
            ) from exc
        # TODO(box): sanity-check threshold 27 against real rushes; drop to
        # AdaptiveDetector if the corporate footage is slow-cut.
        scenes = detect(path, ContentDetector(threshold=self.threshold))
        return [
            Shot(
                index=i,
                startMs=int(start.get_seconds() * 1000),
                endMs=int(end.get_seconds() * 1000),
            )
            for i, (start, end) in enumerate(scenes)
        ]


class Sam2Tracker:
    """SAM2 person segmentation + tracking per shot."""

    def track(self, path: str, shots: list[Shot]) -> list[Track]:
        try:
            import sam2  # noqa: F401  # lazy: GB10-only dep
        except ImportError as exc:
            raise RuntimeError(
                "sam2 runs on the GB10 — install from the wheelhouse"
            ) from exc
        # TODO(box): build the video predictor (sam2.1-hiera-large), prompt
        # with person detections on each shot's first frame, propagate masks,
        # write crops under settings.media_dir, and fill frameQuality
        # (variance-of-Laplacian sharpness, landmark frontality, mean luma).
        raise NotImplementedError("TODO(box): finish Sam2Tracker.track on the GB10")


class InsightFaceEmbedder:
    """InsightFace buffalo_l face vectors (512-dim)."""

    def embed(self, track: Track) -> list[Vector] | None:
        try:
            import insightface  # noqa: F401  # lazy: GB10-only dep
        except ImportError as exc:
            raise RuntimeError(
                "insightface runs on the GB10 — install from the wheelhouse"
            ) from exc
        # TODO(box): run buffalo_l on the track's face crops; return None when
        # detection confidence stays below threshold (that None is what routes
        # a track into body-only clustering — do not return []).
        raise NotImplementedError(
            "TODO(box): finish InsightFaceEmbedder.embed on the GB10"
        )


class Siglip2BodyEmbedder:
    """SigLIP2 visual vectors over body crops — the body-evidence fallback."""

    def embed(self, track: Track) -> list[Vector]:
        try:
            import transformers  # noqa: F401  # lazy: GB10-only dep
        except ImportError as exc:
            raise RuntimeError(
                "siglip2 runs on the GB10 — install from the wheelhouse"
            ) from exc
        # TODO(box): siglip2-base-patch16-224 over body crops, mean-pool.
        raise NotImplementedError(
            "TODO(box): finish Siglip2BodyEmbedder.embed on the GB10"
        )


# ---------------------------------------------------------------- fallback detector


class FixedIntervalDetector:
    """Every-N-seconds pseudo-shots. Zero dependencies, always works.

    Uses ffprobe for the real duration when available; otherwise assumes
    `fallback_duration_s` so the off-box demo works even when the path does
    not exist on this machine.
    """

    def __init__(
        self, interval_s: float = 3.0, fallback_duration_s: float = 12.0
    ) -> None:
        self.interval_s = interval_s
        self.fallback_duration_s = fallback_duration_s

    def _duration_s(self, path: str) -> float:
        try:
            out = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    path,
                ],
                capture_output=True,
                timeout=10,
                check=True,
            )
            return float(json.loads(out.stdout)["format"]["duration"])
        except Exception:  # noqa: BLE001 — no ffprobe / no file is the normal off-box case
            return self.fallback_duration_s

    def detect(self, path: str) -> list[Shot]:
        duration_ms = int(self._duration_s(path) * 1000)
        step_ms = max(int(self.interval_s * 1000), 1)
        shots = []
        for i, start in enumerate(range(0, duration_ms, step_ms)):
            shots.append(
                Shot(index=i, startMs=start, endMs=min(start + step_ms, duration_ms))
            )
        return shots


# ---------------------------------------------------------------- fakes


class FakeDetector:
    def __init__(self, shots: list[Shot]) -> None:
        self._shots = shots

    def detect(self, path: str) -> list[Shot]:
        return list(self._shots)


class FakeTracker:
    def __init__(self, tracks: list[Track]) -> None:
        self._tracks = tracks

    def track(self, path: str, shots: list[Shot]) -> list[Track]:
        # Clamp shot indices so fixtures compose with ANY detector (the demo
        # pairs this with FixedIntervalDetector, whose shot count varies).
        last = max(len(shots) - 1, 0)
        return [
            Track(
                trackId=t.trackId,
                shotIndex=min(t.shotIndex, last),
                frames=list(t.frames),
                bboxes=list(t.bboxes),
                cropPaths=list(t.cropPaths),
                frameQuality=t.frameQuality,
            )
            for t in self._tracks
        ]


class FakeFaceEmbedder:
    def __init__(self, by_track: dict[str, list[Vector] | None]) -> None:
        self._by_track = by_track

    def embed(self, track: Track) -> list[Vector] | None:
        return self._by_track.get(track.trackId)


class FakeBodyEmbedder:
    def __init__(self, by_track: dict[str, list[Vector]]) -> None:
        self._by_track = by_track

    def embed(self, track: Track) -> list[Vector]:
        return self._by_track.get(track.trackId, [])


# ---------------------------------------------------------------- demo fixture
# Hand-written noisy copies of the seeded registry vectors (backend/db/store):
# cosine ≈ 0.99 to their seed, ≈ 0.1 across identities. Six tracks → three
# identities → the demo beat: "3 people found, 2 match approved cast,
# 1 unknown". Deterministic, no RNG.

_NEWCOMER_FACE: Vector = [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _near(vec: Vector, bump: int, eps: float = 0.08) -> Vector:
    out = list(vec)
    out[bump % len(out)] += eps
    return out


def _quality(sharp_frame: int, frames: list[int]) -> dict[int, dict[str, float]]:
    return {
        f: {
            "sharpness": 0.9 if f == sharp_frame else 0.5,
            "frontality": 0.8 if f == sharp_frame else 0.6,
            "brightness": 0.7,
        }
        for f in frames
    }


def demo_tracks() -> list[Track]:
    def mk(track_id: str, shot: int, first_frame: int) -> Track:
        frames = [first_frame, first_frame + 8, first_frame + 16]
        return Track(
            trackId=track_id,
            shotIndex=shot,
            frames=frames,
            bboxes=[(0.3, 0.1, 0.2, 0.7)] * len(frames),
            frameQuality=_quality(first_frame + 8, frames),
        )

    return [
        mk("trk_dana_1", 0, 0),
        mk("trk_dana_2", 1, 90),
        mk("trk_marcus_1", 0, 10),
        mk("trk_marcus_2", 2, 180),
        mk("trk_new_1", 1, 100),
        mk("trk_new_2", 3, 260),
    ]


def demo_fake_analyzers() -> Analyzers:
    faces: dict[str, list[Vector] | None] = {
        "trk_dana_1": [_near(DANA_FACE, 4)],
        "trk_dana_2": [_near(DANA_FACE, 5)],
        "trk_marcus_1": [_near(MARCUS_FACE, 4)],
        "trk_marcus_2": [_near(MARCUS_FACE, 6)],
        "trk_new_1": [_near(_NEWCOMER_FACE, 5)],
        "trk_new_2": [_near(_NEWCOMER_FACE, 7)],
    }
    bodies: dict[str, list[Vector]] = {
        "trk_dana_1": [[1.0, 0.0, 0.0, 0.1]],
        "trk_dana_2": [[0.95, 0.0, 0.0, 0.05]],
        "trk_marcus_1": [[0.0, 1.0, 0.0, 0.1]],
        "trk_marcus_2": [[0.0, 0.95, 0.0, 0.05]],
        "trk_new_1": [[0.0, 0.0, 1.0, 0.1]],
        "trk_new_2": [[0.0, 0.0, 0.95, 0.05]],
    }
    return Analyzers(
        detector=FixedIntervalDetector(),
        tracker=FakeTracker(demo_tracks()),
        face=FakeFaceEmbedder(faces),
        body=FakeBodyEmbedder(bodies),
    )


# ---------------------------------------------------------------- selection


def real_analyzers() -> Analyzers:
    return Analyzers(
        detector=PySceneDetectDetector(),
        tracker=Sam2Tracker(),
        face=InsightFaceEmbedder(),
        body=Siglip2BodyEmbedder(),
    )


def _real_available() -> bool:
    # find_spec is cheap (no import of heavy CUDA stacks at request time).
    # TODO(box): confirm the wheelhouse module names, especially sam2's.
    return all(
        importlib.util.find_spec(m) is not None
        for m in ("scenedetect", "sam2", "insightface")
    )


def choose_analyzers(mode: str | None = None) -> Analyzers:
    """RUSHCUT_ANALYZERS=real|fake, default fake — off-box there is no CV
    stack, and a missing wheel must degrade to fakes, not kill the demo."""
    mode = (mode or os.environ.get("RUSHCUT_ANALYZERS", "fake")).lower()
    if mode == "real":
        if _real_available():
            return real_analyzers()
        print(
            "[ingest] RUSHCUT_ANALYZERS=real but CV wheels missing — falling back to fakes"
        )
    return demo_fake_analyzers()
