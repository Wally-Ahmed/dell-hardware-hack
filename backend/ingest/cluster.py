"""Greedy agglomerative clustering of person tracks into identities.

Pure numpy, deterministic given input order. Two-phase by evidence strength:

1. Tracks WITH a usable face cluster by face embedding (strong biometric
   signal, threshold 0.6).
2. Tracks WITHOUT a face fall back to body embeddings (wardrobe/build — much
   weaker, threshold 0.5): they may join an existing cluster via its members'
   body vectors, else they cluster among themselves, always marked
   lower-confidence.

A cluster that ends the pass with a single member is flagged `unresolved`.
That flag is the product's core rule: an unresolved identity is NEVER
silently dropped — it surfaces to a human. (The pipeline may later resolve a
singleton by matching it to a registered person's stored embeddings; that
decision belongs to the pipeline, which sees the registry — this module only
sees tonight's footage.)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend.ingest.similarity import cosine

FACE_THRESHOLD = 0.6
BODY_THRESHOLD = 0.5


@dataclass
class TrackVectors:
    """Per-track mean embeddings, the unit the clusterer works on."""

    track_id: str
    face: np.ndarray | None = None
    body: np.ndarray | None = None


@dataclass
class Cluster:
    cluster_id: str
    track_ids: list[str] = field(default_factory=list)
    # Members that joined without a face — the "lower-confidence" marking.
    body_only_track_ids: list[str] = field(default_factory=list)
    kind: str = "face"  # "face" | "body" — the evidence the cluster is built on
    confidence: str = "high"  # "high" (face-backed) | "low" (body-only)
    unresolved: bool = False
    reason: str | None = None
    _faces: list[np.ndarray] = field(default_factory=list)
    _bodies: list[np.ndarray] = field(default_factory=list)

    @property
    def face_embedding(self) -> np.ndarray | None:
        return np.mean(np.stack(self._faces), axis=0) if self._faces else None

    @property
    def body_embedding(self) -> np.ndarray | None:
        return np.mean(np.stack(self._bodies), axis=0) if self._bodies else None

    @property
    def embedding(self) -> np.ndarray | None:
        """The cluster's mean embedding — face space when available."""
        return self.face_embedding if self._faces else self.body_embedding

    def _add(self, tv: TrackVectors, body_only: bool) -> None:
        self.track_ids.append(tv.track_id)
        if body_only:
            self.body_only_track_ids.append(tv.track_id)
        if tv.face is not None and not body_only:
            self._faces.append(np.asarray(tv.face, dtype=np.float64))
        if tv.body is not None:
            self._bodies.append(np.asarray(tv.body, dtype=np.float64))


def cluster_tracks(
    tracks: list[TrackVectors],
    face_threshold: float = FACE_THRESHOLD,
    body_threshold: float = BODY_THRESHOLD,
) -> list[Cluster]:
    """Greedy single-pass assign-or-create in input order.

    Each track joins the best-scoring existing cluster above threshold
    (compared against the cluster's CURRENT mean, which sharpens as members
    join) or starts a new one. Ties break toward the earliest cluster via
    strict `>` comparison — fully deterministic for a given input order.
    """
    clusters: list[Cluster] = []

    def best(
        candidates: list[tuple[Cluster, float]], threshold: float
    ) -> Cluster | None:
        top: Cluster | None = None
        top_score = threshold
        for cl, score in candidates:
            if score > top_score or (top is None and score >= threshold):
                top, top_score = cl, score
        return top

    # Phase 1 — faces first: strongest evidence claims cluster identity.
    faceless: list[TrackVectors] = []
    for tv in tracks:
        if tv.face is None:
            faceless.append(tv)
            continue
        scored = [
            (cl, cosine(tv.face, cl.face_embedding))
            for cl in clusters
            if cl.face_embedding is not None
        ]
        target = best(scored, face_threshold)
        if target is None:
            target = Cluster(cluster_id="", kind="face", confidence="high")
            clusters.append(target)
        target._add(tv, body_only=False)

    # Phase 2 — faceless tracks: join any cluster through its body mean, else
    # cluster among themselves. Either way the membership is lower-confidence.
    for tv in faceless:
        if tv.body is None:
            # No evidence at all — still never dropped, it becomes an
            # unresolved singleton below.
            cl = Cluster(cluster_id="", kind="body", confidence="low")
            cl.track_ids.append(tv.track_id)
            cl.body_only_track_ids.append(tv.track_id)
            clusters.append(cl)
            continue
        scored = [
            (cl, cosine(tv.body, cl.body_embedding))
            for cl in clusters
            if cl.body_embedding is not None
        ]
        target = best(scored, body_threshold)
        if target is None:
            target = Cluster(cluster_id="", kind="body", confidence="low")
            clusters.append(target)
        target._add(tv, body_only=True)

    # Phase 3 — flag singletons. One track that matched nothing is not an
    # identity we can trust; a human decides (background-character rule).
    for i, cl in enumerate(clusters):
        cl.cluster_id = f"cls_{i:03d}"
        if len(cl.track_ids) == 1:
            cl.unresolved = True
            cl.reason = (
                "no usable face"
                if cl.kind == "body"
                else "matched no other track above face threshold"
            )
    return clusters
