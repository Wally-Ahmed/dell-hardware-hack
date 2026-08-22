# backend/ingest — ingest + cast registry (Role D)

## Mount (conductor)

In `backend/app.py`, replace the `people_stub` mount with:

```python
from backend.ingest.router import router as ingest_router

app.include_router(ingest_router)  # instead of app.include_router(people_stub)
```

The router serves `GET /people`, `POST /people/{id}/policy` (same shapes as the mock,
now repo-backed with the same three seeds), plus `POST /ingest/footage` → `{ingestId}`
and `GET /ingest/{ingestId}`. Progress lines go out over the existing ws hub as
`{"kind": "log", "jobId": "<ingestId>", ...}`.

Storage: MongoDB via motor when `MONGODB_URI` answers a ping within 1 s, otherwise an
in-memory store with the same interface (one printed warning). Nothing to configure
off-box.

## Analyzers: fake ↔ real

`RUSHCUT_ANALYZERS=fake` (default) runs FixedIntervalDetector + fixture-fed fakes —
the demo beat ("3 people found, 2 match approved cast, 1 unknown") works on any
laptop with no CV stack. `RUSHCUT_ANALYZERS=real` selects the real adapters when the
wheels are importable, and falls back to fakes (with a printed warning) when not.

## Finishing the real adapters on the box

1. `pip install --no-index --find-links <nvme>/wheels scenedetect insightface transformers` (+ the sam2 wheel).
2. `grep -rn "TODO(box)" backend/ingest/analyzers.py` — finish `Sam2Tracker.track`
   (propagate masks per shot, write crops, fill `Track.frameQuality`),
   `InsightFaceEmbedder.embed` (buffalo_l; return `None` when no usable face — that is
   what routes a track into body-only clustering), `Siglip2BodyEmbedder.embed`.
3. `PySceneDetectDetector` is already functional once scenedetect imports.
4. `export RUSHCUT_ANALYZERS=real`. First real ingest appends 512-dim InsightFace
   vectors next to the 8-dim demo seed vectors; matching skips mismatched dimensions,
   so no migration is needed (delete the demo vectors whenever real refs exist).

## Tests

```bash
/tmp/mockvenv/bin/python -m pytest backend/ingest/tests/ -x -q
```

No network, no Mongo, no CV deps — in-memory store + fakes only.
