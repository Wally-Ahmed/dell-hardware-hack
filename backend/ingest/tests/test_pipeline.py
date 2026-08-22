"""End-to-end ingest with fakes: seeds match, new person created, unresolved
surfaced — and NEVER dropped. No network, no Mongo, no CV deps."""

from __future__ import annotations

import asyncio

from backend.db.store import DANA_FACE, MARCUS_FACE, MOCK_PROJECT_ID, memory_store
from backend.ingest.analyzers import (
    Analyzers,
    FakeBodyEmbedder,
    FakeDetector,
    FakeFaceEmbedder,
    FakeTracker,
    Shot,
    Track,
)
from backend.ingest.pipeline import ingest_footage

NEWCOMER_FACE = [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def near(base: list[float], bump: int, eps: float = 0.08) -> list[float]:
    v = list(base)
    v[bump % len(v)] += eps
    return v


def _track(tid: str, shot: int, first: int) -> Track:
    return Track(
        trackId=tid,
        shotIndex=shot,
        frames=[first, first + 8],
        bboxes=[(0.3, 0.1, 0.2, 0.7)] * 2,
        frameQuality={
            first: {"sharpness": 0.4, "frontality": 0.5, "brightness": 0.6},
            first + 8: {"sharpness": 0.9, "frontality": 0.8, "brightness": 0.7},
        },
    )


def _fixture_analyzers() -> Analyzers:
    shots = [Shot(0, 0, 4000), Shot(1, 4000, 9000)]
    tracks = [
        _track("trk_dana_a", 0, 0),
        _track("trk_dana_b", 1, 120),
        _track("trk_marcus_a", 0, 10),  # single track — resolved via the registry
        _track("trk_new_a", 1, 130),
        _track("trk_new_b", 1, 150),
        _track("trk_ghost", 0, 20),  # no face, body matches nobody
    ]
    faces = {
        "trk_dana_a": [near(DANA_FACE, 4)],
        "trk_dana_b": [near(DANA_FACE, 5)],
        "trk_marcus_a": [near(MARCUS_FACE, 4)],
        "trk_new_a": [near(NEWCOMER_FACE, 5)],
        "trk_new_b": [near(NEWCOMER_FACE, 6)],
        "trk_ghost": None,
    }
    bodies = {
        "trk_dana_a": [[1.0, 0.0, 0.0, 0.0]],
        "trk_dana_b": [[0.95, 0.05, 0.0, 0.0]],
        "trk_marcus_a": [[0.0, 1.0, 0.0, 0.0]],
        "trk_new_a": [[0.0, 0.0, 1.0, 0.0]],
        "trk_new_b": [[0.0, 0.05, 0.95, 0.0]],
        "trk_ghost": [[0.0, 0.0, 0.0, 1.0]],
    }
    return Analyzers(
        detector=FakeDetector(shots),
        tracker=FakeTracker(tracks),
        face=FakeFaceEmbedder(faces),
        body=FakeBodyEmbedder(bodies),
    )


def test_pipeline_end_to_end() -> None:
    async def run() -> None:
        store = memory_store()
        lines: list[str] = []

        async def emit(job_id: str, line: str) -> None:
            lines.append(line)

        summary = await ingest_footage(
            MOCK_PROJECT_ID,
            "/media/raw/lobby_rushes.mp4",
            analyzers=_fixture_analyzers(),
            people_repo=store.people,
            emit_log=emit,
            ingest_id="ing_test",
        )

        assert summary == {
            "shots": 2,
            "tracks": 6,
            "people": {"matched": 2, "new": 1, "unresolved": 1},
        }

        people = await store.people.list(MOCK_PROJECT_ID)
        # 3 seeds + 1 new + 1 unresolved. The unresolved track was NOT dropped.
        assert len(people) == 5
        by_id = {p["_id"]: p for p in people}

        # Matched principals accumulated the new footage's embeddings.
        assert len(by_id["per_dana"]["faceEmbeddings"]) == 1 + 2
        assert len(by_id["per_marcus"]["faceEmbeddings"]) == 1 + 1
        assert by_id["per_dana"]["policy"] == "approved"  # matching never edits policy

        newcomers = [
            p for p in people if p["_id"].startswith("per_") and "sourceTracks" in p
        ]
        new_person = next(p for p in newcomers if not p.get("unresolved"))
        ghost = next(p for p in newcomers if p.get("unresolved"))

        assert new_person["policy"] == "unknown"
        assert new_person["name"] is None
        assert new_person["role"] == "background"
        assert sorted(new_person["sourceTracks"]) == ["trk_new_a", "trk_new_b"]
        assert new_person["refSpecs"], "new people carry best-frame crop specs"
        # The weighted quality picked the sharp frontal frame for the crops.
        assert new_person["refSpecs"][0]["frame"] in (138, 158)

        assert ghost["policy"] == "unknown"
        assert ghost["unresolved"] is True
        assert ghost["unresolvedReason"] == "no usable face"
        assert ghost["sourceTracks"] == ["trk_ghost"]

        # The demo beat line went out over the log stream.
        assert any(
            "4 people found, 2 match approved cast, 2 unknown" in line for line in lines
        )

    asyncio.run(run())


def test_singleton_matching_registry_is_resolved_not_unresolved() -> None:
    """One clean track of a registered person must resolve via stored
    embeddings — that is what the registry is FOR."""

    async def run() -> None:
        store = memory_store()

        async def emit(job_id: str, line: str) -> None:
            return None

        analyzers = Analyzers(
            detector=FakeDetector([Shot(0, 0, 3000)]),
            tracker=FakeTracker([_track("trk_solo_marcus", 0, 0)]),
            face=FakeFaceEmbedder({"trk_solo_marcus": [near(MARCUS_FACE, 5)]}),
            body=FakeBodyEmbedder({}),
        )
        summary = await ingest_footage(
            MOCK_PROJECT_ID,
            "/media/raw/solo.mp4",
            analyzers=analyzers,
            people_repo=store.people,
            emit_log=emit,
        )
        assert summary["people"] == {"matched": 1, "new": 0, "unresolved": 0}

    asyncio.run(run())
