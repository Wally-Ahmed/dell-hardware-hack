"""ingest_footage — shots → tracks → embeddings → identity clusters → cast registry.

The output is the Cast panel's data: every identity seen in the footage
becomes (or updates) a person in the registry. The product's core rule is
enforced here: an unresolved track is NEVER silently dropped — it becomes a
person with `unresolved: true` and a reason, surfaced for a human to approve
or remove (background-character rule).

Analyzer calls run in a worker thread (`asyncio.to_thread`) because the real
adapters block on GPU/IO for minutes and this coroutine shares the event loop
with the websocket hub.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np

from backend.db.store import PeopleRepo, _oid
from backend.ingest.analyzers import Analyzers, Track
from backend.ingest.cluster import Cluster, TrackVectors, cluster_tracks
from backend.ingest.refs import crop_specs, frame_score
from backend.ingest.similarity import cosine

# A cluster whose mean face lands at ≥0.65 against a person's stored vectors
# IS that person. Looser than the 0.6 in-footage threshold on purpose: stored
# registry vectors come from different days/lighting than tonight's rushes.
FACE_MATCH_THRESHOLD = 0.65

EmitLog = Callable[[str, str], Awaitable[None]]  # hub.log-compatible: (jobId, line)

_NEUTRAL_QUALITY = {"sharpness": 0.5, "frontality": 0.5, "brightness": 0.5}


def _mean(vectors: list[list[float]] | None) -> np.ndarray | None:
    if not vectors:
        return None
    return np.mean(np.asarray(vectors, dtype=np.float64), axis=0)


def _best_person_match(
    cluster_face: np.ndarray, people: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, float]:
    """Max cosine against each person's stored face vectors. Stored vectors
    with a different dimension (8-dim demo seeds vs 512-dim InsightFace) are
    skipped, not crashed on — the two generations must coexist on the box."""
    best, best_score = None, FACE_MATCH_THRESHOLD
    for person in people:
        score = 0.0
        for stored in person.get("faceEmbeddings", []):
            if len(stored) != cluster_face.shape[0]:
                continue
            score = max(score, cosine(cluster_face, stored))
        if score > best_score or (best is None and score >= FACE_MATCH_THRESHOLD):
            best, best_score = person, score
    return best, best_score if best else 0.0


def _merged_quality(tracks: list[Track]) -> dict[int, dict[str, float]]:
    """Union of member tracks' per-frame quality; on a frame collision the
    higher-scoring entry wins (deterministic). Missing quality gets a neutral
    0.5 so off-box fixtures without quality still yield ref specs."""
    merged: dict[int, dict[str, float]] = {}
    for track in tracks:
        quality = track.frameQuality or {
            f: dict(_NEUTRAL_QUALITY) for f in track.frames
        }
        for frame, q in quality.items():
            if frame not in merged or frame_score(q) > frame_score(merged[frame]):
                merged[frame] = dict(q)
    return merged


def _new_person_doc(
    project_id: str,
    cluster: Cluster,
    member_tracks: list[Track],
    faces: list[list[float]],
    bodies: list[list[float]],
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "_id": _oid("per"),
        "projectId": project_id,
        "name": None,
        # Unnamed detections default to background — the rule that turns
        # recurring extras from a hazard into an asset (CLAUDE.md §3.5).
        "role": "background",
        "policy": "unknown",
        # No crops exist off-box; refSpecs tell the box's crop stage exactly
        # which frames to cut, then it fills these urls.
        "refs": {"face": None, "body": None, "wardrobe": None},
        "refSpecs": crop_specs(_merged_quality(member_tracks)),
        "consent": None,
        "faceEmbeddings": faces,
        "bodyEmbeddings": bodies,
        "sourceTracks": list(cluster.track_ids),
        "confidence": cluster.confidence,
    }
    if cluster.unresolved:
        doc["unresolved"] = True
        doc["unresolvedReason"] = cluster.reason
    return doc


async def ingest_footage(
    project_id: str,
    path: str,
    analyzers: Analyzers,
    people_repo: PeopleRepo,
    emit_log: EmitLog,
    *,
    ingest_id: str = "ingest",
) -> dict[str, Any]:
    """Run the full ingest and return the demo-beat summary:
    {shots, tracks, people: {matched, new, unresolved}}."""
    await emit_log(ingest_id, f"ingest: analyzing {path}")
    shots = await asyncio.to_thread(analyzers.detector.detect, path)
    await emit_log(ingest_id, f"ingest: {len(shots)} shots detected")

    tracks = await asyncio.to_thread(analyzers.tracker.track, path, shots)
    await emit_log(ingest_id, f"ingest: {len(tracks)} person tracks")

    # Per-track mean embeddings — the per-track mean is the stable unit we
    # cluster on and later append to the registry (bounded growth, robust to
    # a couple of bad frames).
    by_id: dict[str, Track] = {t.trackId: t for t in tracks}
    track_vectors: list[TrackVectors] = []
    for track in tracks:
        face_vecs = await asyncio.to_thread(analyzers.face.embed, track)
        body_vecs = await asyncio.to_thread(analyzers.body.embed, track)
        track_vectors.append(
            TrackVectors(
                track_id=track.trackId, face=_mean(face_vecs), body=_mean(body_vecs)
            )
        )

    clusters = cluster_tracks(track_vectors)
    await emit_log(
        ingest_id,
        f"ingest: {len(clusters)} identity clusters "
        f"({sum(1 for c in clusters if c.unresolved)} unresolved before registry match)",
    )

    # list() seeds Dana/Marcus/unknown on first touch of a project.
    people = await people_repo.list(project_id)
    vec_by_track = {tv.track_id: tv for tv in track_vectors}
    matched = new = unresolved = 0

    for cl in clusters:
        member_tracks = [by_id[tid] for tid in cl.track_ids]
        faces = [
            vec_by_track[tid].face.tolist()
            for tid in cl.track_ids
            if vec_by_track[tid].face is not None
        ]
        bodies = [
            vec_by_track[tid].body.tolist()
            for tid in cl.track_ids
            if vec_by_track[tid].body is not None
        ]

        # Registry match runs for EVERY face-bearing cluster, including
        # unresolved singletons: one clean track of a registered person is
        # exactly what stored embeddings are for — the match resolves it.
        person = None
        if cl.face_embedding is not None:
            person, score = _best_person_match(cl.face_embedding, people)

        if person is not None:
            person.setdefault("faceEmbeddings", []).extend(faces)
            person.setdefault("bodyEmbeddings", []).extend(bodies)
            await people_repo.upsert(person)
            matched += 1
            label = person.get("name") or person["_id"]
            await emit_log(
                ingest_id,
                f"ingest: cluster {cl.cluster_id} matched {label} "
                f"(cos {score:.2f}, policy {person.get('policy')})",
            )
            continue

        doc = _new_person_doc(project_id, cl, member_tracks, faces, bodies)
        await people_repo.upsert(doc)
        if cl.unresolved:
            unresolved += 1
            await emit_log(
                ingest_id,
                f"ingest: cluster {cl.cluster_id} UNRESOLVED ({cl.reason}) — "
                f"kept as {doc['_id']} for human review, never dropped",
            )
        else:
            new += 1
            await emit_log(
                ingest_id,
                f"ingest: cluster {cl.cluster_id} is a new person {doc['_id']} (policy unknown)",
            )

    total = matched + new + unresolved
    await emit_log(
        ingest_id,
        f"{total} people found, {matched} match approved cast, "
        f"{new + unresolved} unknown — approve or remove?",
    )
    return {
        "shots": len(shots),
        "tracks": len(tracks),
        "people": {"matched": matched, "new": new, "unresolved": unresolved},
    }
