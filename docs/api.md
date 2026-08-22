# The Contract

**This file lands on `main` before anyone branches. After 13:30 it changes only by agreement
between roles B (backend), C (editor), and D (ingest).**

Everything below is what lets four people build against a mock while the GB10 is still being
provisioned. If you find yourself guessing at a shape, stop and fix it here instead.

Base URL: `http://localhost:8000`. Progress arrives over `ws://localhost:8000/ws`.

---

## 1. Jobs — the one cross-cutting seam

A job is anything slow: generation, ingest, policy enforcement, upscale, render. The editor
never blocks on one.

### Job states

```
queued → running → (policy_check) → complete
                 ↘ failed
                 ↘ cancelled
                 ↘ policy_blocked      # generated output contained an unapproved person
```

`policy_blocked` is not a failure — it is the consent registry doing its job, and the UI should
say so. It carries the remediation that was attempted.

### Job object

```jsonc
{
  "jobId": "job_01J8X...",           // stable, opaque, client never parses it
  "projectId": "proj_01J8W...",
  "type": "generate_shot",           // see §3 tool names
  "state": "running",
  "progress": 0.42,                  // 0.0–1.0, or null if indeterminate
  "stage": "video",                  // analyze|references|keyframe|video|policy_check|finalize
  "message": "Wan 2.2 I2V, step 3/4",// human-readable, safe to render directly
  "createdAt": "2026-08-22T17:45:12Z",
  "startedAt": "2026-08-22T17:45:19Z",
  "finishedAt": null,
  "result": null,                    // populated on `complete`, see §2
  "error": null,                     // { "code": "...", "message": "..." } on `failed`
  "policy": null                     // see below, populated on policy_check / policy_blocked
}
```

### Policy block payload

```jsonc
"policy": {
  "verdict": "blocked",              // "clear" | "blocked" | "needs_review"
  "unapproved": [
    { "trackId": "trk_7", "personId": null, "confidence": 0.81,
      "frames": [12, 13, 14], "cropUrl": "/media/tmp/trk_7.jpg" }
  ],
  "unresolved": [                    // NEVER auto-passed. Always surfaced to a human.
    { "trackId": "trk_9", "reason": "no usable face", "cropUrl": "/media/tmp/trk_9.jpg" }
  ],
  "remediation": "inpaint",          // "inpaint" | "regenerate" | "rejected" | null
  "remediatedAssetId": "ast_01J8Y..."
}
```

### Endpoints

| Method | Path | Notes |
|---|---|---|
| `POST` | `/jobs` | Body `{ type, projectId, params }` → returns a Job in `queued` |
| `GET` | `/jobs/{jobId}` | Poll fallback if the socket drops |
| `POST` | `/jobs/{jobId}/cancel` | Best-effort |
| `GET` | `/jobs?projectId=&state=` | Queue view for the Models/Jobs panel |

### WebSocket frames

One envelope, always:

```jsonc
{ "kind": "job", "job": { /* full Job object */ } }
{ "kind": "log",  "jobId": "job_...", "line": "loading wan2.2_i2v_high..." }
{ "kind": "models", "models": [ /* see §4 */ ] }
```

Send the **whole** job object on every change. Do not send deltas — reconciling partial state
across three people's code at 16:00 is not a fight worth having.

---

## 2. Assets and provenance

Every generated asset carries where it came from. This is both good engineering and the
consent story made auditable.

```jsonc
{
  "assetId": "ast_01J8Y...",
  "projectId": "proj_01J8W...",
  "kind": "video",                   // "image" | "video" | "audio"
  "url": "/media/gen/ast_01J8Y.mp4",
  "posterUrl": "/media/gen/ast_01J8Y.jpg",
  "width": 1280, "height": 720, "fps": 24, "durationMs": 5000,
  "provenance": {
    "model": "wan2.2_i2v_high_noise_14B_fp8_scaled",
    "precision": "fp8",
    "prompt": "low-angle push-in, Dana crossing the lobby",
    "negativePrompt": "additional people, crowd, bystanders",
    "seed": 881203,
    "references": ["ast_01J8T...", "ast_01J8U..."],
    "parentAssetId": "ast_01J8S...",  // what it was derived from, null if original
    "jobId": "job_01J8X...",
    "workflow": "wan14b_i2v_lightning",
    "policyVerdict": "clear",
    "approvedBy": "wally",
    "approvedAt": "2026-08-22T18:02:41Z"
  }
}
```

---

## 3. Agent tools

**Hard cap: 20–30 tools.** Measured elsewhere: tool-selection accuracy collapses from ~95% to
~71% once a large toolset is loaded. Keep them flat, JSON-schema'd, idempotent, JSON-returning.

Every tool references objects by **stable id, never ordinal position**.

| Tier | Tools | Behavior |
|---|---|---|
| **1 — act directly** (cheap, reversible) | `list_cast`, `search_memory`, `list_models`, `model_status`, `job_status`, `describe_shot`, `set_marker` | Agent just does it |
| **2 — propose, human applies** | `add_to_timeline`, `retime_clip`, `swap_shot`, `set_cast_policy` | Opens an edit session; applies as **one** undoable command or is rejected |
| **3 — plan → approve → run** | `generate_keyframe`, `generate_shot`, `reangle_shot`, `remove_person`, `replace_person`, `enforce_cast_policy`, `upscale`, `interpolate`, `ingest_footage`, `render`, `load_model`, `unload_model` | Agent shows references, model, estimated time; runs only on approval; results land in the bin as **candidates**, never in the cut |

### Edit sessions (tier 2 and 3)

There must be **no path — internal or external — that reaches the working timeline without
passing through a session.**

```
POST /sessions              → { sessionId }        # isolated draft, working project untouched
POST /sessions/{id}/ops     → { ok, staleIds: [] } # agent's edits land here
GET  /sessions/{id}/preview → timeline JSON        # what the human previews
POST /sessions/{id}/review  → { applied: true }    # atomic — ONE undo step, or rejected
```

`staleIds` is how we catch a proposal built against a timeline the human has since changed.

---

## 4. Models

`GET /models` returns the registry plus live state. Same source feeds the agent's `list_models`
and the Models panel.

```jsonc
{
  "id": "wan2.2_ti2v_5B",
  "task": "t2v",                     // t2i|edit|multiref|t2v|i2v|v2v-reangle|inpaint|animate|
                                     // segment|face-id|depth|embed|upscale-image|upscale-video|interpolate
  "tier": "draft",                   // "draft" | "hero"
  "precision": "fp16",
  "approxGb": 11.2,
  "loadSeconds": 18,
  "license": "Apache-2.0",
  "bestFor": "Fast 720p24 previews under 9 minutes. Use for anything the user is iterating on.",
  "state": "resident",               // "idle" | "loading" | "resident" | "evicting"
  "pinned": false
}
```

`bestFor` is the line the agent reads when it chooses a model. Write it for an LLM, not for a
changelog.

---

## 5. MongoDB collections

`mongod` runs on the box, bound to localhost. Database `rushcut`.

| Collection | Key fields |
|---|---|
| `projects` | `_id`, `name`, `fps`, `resolution`, `createdAt` |
| `media` | `_id`, `projectId`, `path`, `kind`, `durationMs`, `probe` |
| `shots` | `_id`, `projectId`, `mediaId`, `startMs`, `endMs`, `contactSheetUrl` |
| `people` | `_id`, `projectId`, `name`, `role`, `policy`, `faceEmbeddings[]`, `bodyEmbeddings[]`, `refs{face,body,wardrobe}`, `consent{}` |
| `scenes` | `_id`, `projectId`, `environmentRefs[]`, `lightingNotes` |
| `generations` | `_id`, `projectId`, `jobId`, provenance block from §2 |
| `notes` | `_id`, `projectId`, `text`, `embedding[]` |

**Every document carries `projectId` from the first write.** Multi-project is nearly free today
and painful to retrofit tomorrow.

### Vector search — the pragmatic call

MongoDB Community now supports native vector search self-managed, but it deploys as a separate
search-node process and we are **not** betting tonight's demo on standing that up on aarch64.

**Tonight:** store embeddings as plain arrays in the documents and do brute-force cosine
similarity in numpy. At demo scale (hundreds to a few thousand vectors) that is microseconds.
Role A can add a real search node later if the afternoon goes well.

### `people.policy`

```jsonc
"policy": "approved"   // "approved" | "unknown" | "remove"
"role":   "principal"  // "principal" | "background" | "bystander"
"consent": {
  "recordUrl": "/media/consent/dana_signed.pdf",
  "scope": "Project Atlas — corporate brand film, all media, 2 years",
  "noticeAt": "2026-08-20T09:00:00Z",
  "signedAt": "2026-08-22T08:15:00Z",
  "revokedAt": null
}
```

Recurring extras who must stay consistent get their own entry with `role: "background"` — that
turns them from a hazard into an asset.

---

## 6. Mock server

`backend/mock/app.py` serves every endpoint above with canned data and a fake job that walks
`queued → running → complete` over about eight seconds, emitting real WebSocket frames.

```bash
uvicorn backend.mock.app:app --reload --port 8000
```

Build against this until Role A's smoke test goes green. Do not wait for the box.
