"""Best-frame selection: the sharp frontal frame must win."""

from __future__ import annotations

from backend.ingest.refs import crop_specs, frame_score, pick_best_frames

QUALITY = {
    # blurry but frontal and bright
    0: {"sharpness": 0.2, "frontality": 0.9, "brightness": 0.9},
    # sharp AND frontal — the reference we want
    1: {"sharpness": 0.95, "frontality": 0.9, "brightness": 0.7},
    # sharp but a profile view
    2: {"sharpness": 0.95, "frontality": 0.2, "brightness": 0.9},
}


def test_sharp_frontal_frame_wins() -> None:
    assert pick_best_frames(QUALITY, n=1) == [1]
    # Weighting, not any single metric, decides the runner-up order.
    assert pick_best_frames(QUALITY, n=3) == [1, 2, 0]


def test_missing_metric_drags_score_down() -> None:
    assert frame_score({"sharpness": 1.0}) == 0.5  # frontality/brightness count as 0


def test_ties_break_toward_earlier_frame() -> None:
    q = {7: {"sharpness": 0.5}, 3: {"sharpness": 0.5}}
    assert pick_best_frames(q, n=2) == [3, 7]


def test_crop_specs_shapes() -> None:
    specs = crop_specs(QUALITY, top_n=2)
    # Best frame carries all three kinds; runner-up only face/body.
    assert {"frame": 1, "kind": "face"} in specs
    assert {"frame": 1, "kind": "body"} in specs
    assert [s for s in specs if s["kind"] == "wardrobe"] == [
        {"frame": 1, "kind": "wardrobe"}
    ]
    assert {"frame": 2, "kind": "face"} in specs
    assert all(s["kind"] in ("face", "body", "wardrobe") for s in specs)
