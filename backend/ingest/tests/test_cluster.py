"""Clustering: identity grouping, face+body evidence merge, unresolved flags."""

from __future__ import annotations

from backend.ingest.cluster import TrackVectors, cluster_tracks

DIM = 8


def unit(axis: int, dim: int = DIM) -> list[float]:
    v = [0.0] * dim
    v[axis] = 1.0
    return v


def near(base: list[float], bump: int, eps: float = 0.08) -> list[float]:
    v = list(base)
    v[bump % len(v)] += eps
    return v


def _two_identities_plus_orphan() -> list[TrackVectors]:
    import numpy as np

    def tv(tid: str, face: list[float]) -> TrackVectors:
        return TrackVectors(track_id=tid, face=np.asarray(face))

    return [
        tv("trk_a1", unit(0)),
        tv("trk_a2", near(unit(0), 4)),
        tv("trk_a3", near(unit(0), 5)),
        tv("trk_b1", unit(1)),
        tv("trk_b2", near(unit(1), 4)),
        tv("trk_b3", near(unit(1), 6)),
        tv("trk_orphan", unit(3)),  # far from both identities
    ]


def test_two_identities_and_orphan() -> None:
    clusters = cluster_tracks(_two_identities_plus_orphan())

    assert len(clusters) == 3
    resolved = [c for c in clusters if not c.unresolved]
    orphans = [c for c in clusters if c.unresolved]
    assert len(resolved) == 2
    assert sorted(len(c.track_ids) for c in resolved) == [3, 3]
    assert {tid for c in resolved for tid in c.track_ids} == {
        "trk_a1",
        "trk_a2",
        "trk_a3",
        "trk_b1",
        "trk_b2",
        "trk_b3",
    }
    # The orphan is a singleton, flagged — never silently dropped.
    assert len(orphans) == 1
    assert orphans[0].track_ids == ["trk_orphan"]
    assert orphans[0].reason is not None
    # Mean embedding exists for every cluster.
    assert all(c.embedding is not None for c in clusters)


def test_clustering_is_deterministic() -> None:
    def snapshot() -> list[tuple[str, tuple[str, ...], bool, str]]:
        return [
            (c.cluster_id, tuple(c.track_ids), c.unresolved, c.kind)
            for c in cluster_tracks(_two_identities_plus_orphan())
        ]

    assert snapshot() == snapshot()


def test_faceless_track_joins_by_body_above_threshold() -> None:
    import numpy as np

    a_body = [1.0, 0.0, 0.0, 0.0]
    tracks = [
        TrackVectors("trk_f1", face=np.asarray(unit(0)), body=np.asarray(a_body)),
        TrackVectors(
            "trk_f2",
            face=np.asarray(near(unit(0), 4)),
            body=np.asarray([0.95, 0.05, 0.0, 0.0]),
        ),
        # No face — but the wardrobe/body matches identity A strongly.
        TrackVectors("trk_no_face", face=None, body=np.asarray([0.97, 0.03, 0.0, 0.0])),
    ]
    clusters = cluster_tracks(tracks)

    assert len(clusters) == 1
    cl = clusters[0]
    assert cl.track_ids == ["trk_f1", "trk_f2", "trk_no_face"]
    # The join happened on body evidence and is marked lower-confidence.
    assert cl.body_only_track_ids == ["trk_no_face"]
    assert cl.kind == "face"
    assert not cl.unresolved


def test_faceless_track_below_body_threshold_is_unresolved() -> None:
    import numpy as np

    tracks = [
        TrackVectors(
            "trk_f1", face=np.asarray(unit(0)), body=np.asarray([1.0, 0.0, 0.0, 0.0])
        ),
        TrackVectors(
            "trk_f2",
            face=np.asarray(near(unit(0), 4)),
            body=np.asarray([0.95, 0.05, 0.0, 0.0]),
        ),
        # No face, and the body matches nothing → must surface as unresolved.
        TrackVectors("trk_ghost", face=None, body=np.asarray([0.0, 0.0, 1.0, 0.0])),
    ]
    clusters = cluster_tracks(tracks)

    assert len(clusters) == 2
    ghost = next(c for c in clusters if "trk_ghost" in c.track_ids)
    assert ghost.unresolved
    assert ghost.reason == "no usable face"
    assert ghost.kind == "body"
    assert ghost.confidence == "low"
