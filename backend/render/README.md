# backend/render — timeline JSON → MP4 (ffmpeg)

**Role B: mount with one line in `backend/app.py`:**

```python
from backend.render.router import router as render_router  # then:

app.include_router(render_router)
```

That exposes:

| Method | Path | Notes |
|---|---|---|
| `POST` | `/render` | Body `{projectId, timeline, filename?}` → `{renderId}`; encodes into `settings.media_dir/renders/` in a background task |
| `GET` | `/render/{renderId}` | `{state: rendering\|complete\|failed, progress, path?}` (`durationMs` on complete, `error` tail on failed); unknown id → house `{"error": {...}}` shape |

Progress is broadcast on the shared ws hub as `{"kind": "log", "jobId": renderId, ...}`
lines at 10% steps, so the existing log panel shows it with zero new frontend code.

## Timeline shape

The `GET /sessions/{sid}/preview` shape, extended minimally per clip:

- `assetPath` — absolute file path; tonight the renderer resolves it directly
  (assetId → path via the media store is a TODO wired by the conductor later)
- `inMs` — source in-point, default 0

Gaps between `startMs` offsets render as black. Audio is ignored tonight —
demo clips are MOS; adding it is a straight extension (see `ffmpeg.py` docstring).

| File | What |
|---|---|
| `ffmpeg.py` | `build_filtergraph`, `render` (async subprocess + progress), `ffprobe_duration_ms` |
| `router.py` | FastAPI router + in-memory render registry |
| `tests/` | `python -m pytest backend/render/tests/ -x -q` (integration auto-skips without ffmpeg) |
