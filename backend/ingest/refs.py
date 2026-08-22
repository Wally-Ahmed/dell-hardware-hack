"""Best-frame selection for reference crops. Pure — dicts in, specs out.

Weights (must sum to 1.0):

- sharpness 0.5 — a blurry reference poisons every downstream generation, so
  it dominates.
- frontality 0.3 — face ID and keyframe conditioning both want a frontal
  view, but a sharp three-quarter beats a soft mugshot.
- brightness 0.2 — exposure is the most recoverable in post, so it matters
  least. Scores arrive pre-normalized 0..1 (1 = well exposed), producer's job.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

WEIGHTS: dict[str, float] = {"sharpness": 0.5, "frontality": 0.3, "brightness": 0.2}

# One reference crop of each kind per person is what the people doc carries
# (refs{face,body,wardrobe}); extra face/body frames give the box alternates.
CROP_KINDS = ("face", "body", "wardrobe")


def frame_score(quality: Mapping[str, float]) -> float:
    """Weighted quality score; missing metrics score 0 so they drag the frame
    down instead of silently inflating it."""
    return sum(w * float(quality.get(metric, 0.0)) for metric, w in WEIGHTS.items())


def pick_best_frames(
    quality_by_frame: Mapping[int, Mapping[str, float]], n: int = 3
) -> list[int]:
    """Top-n frame indices by weighted score, best first. Ties break toward
    the earlier frame — deterministic given identical input."""
    ranked = sorted(
        quality_by_frame, key=lambda f: (-frame_score(quality_by_frame[f]), f)
    )
    return ranked[: max(n, 0)]


def crop_specs(
    quality_by_frame: Mapping[int, Mapping[str, float]], top_n: int = 3
) -> list[dict[str, Any]]:
    """Crop specs {frame, kind} for the box's crop stage.

    The single best frame yields all three kinds — wardrobe wants exactly one
    canonical, fullest view. Runner-up frames yield face+body alternates so a
    stale wardrobe never blocks a usable face ref.
    """
    frames = pick_best_frames(quality_by_frame, top_n)
    specs: list[dict[str, Any]] = []
    for rank, frame in enumerate(frames):
        kinds = CROP_KINDS if rank == 0 else ("face", "body")
        specs.extend({"frame": int(frame), "kind": kind} for kind in kinds)
    return specs
