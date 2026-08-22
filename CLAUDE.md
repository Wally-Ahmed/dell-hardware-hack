# CLAUDE.md — Local AI Video Editor (hackathon build)

This file is the full handoff from the planning conversation. Read it completely before touching any files. When in doubt, favor the simplest thing that demos.

## 1. The situation

- One-day hackathon, **today, 22 Aug 2026**. Live demo + pitch this evening. Teams of 2–4.
- Hard rules: **everything runs locally on the box. No cloud APIs of any kind** (no LLM APIs, no hosted generation, no telemetry). Judges may watch the network.
- Target box: **Dell Pro Max with NVIDIA GB10** — Linux **aarch64**, Ubuntu 24.04, Python 3.12, CUDA 13, **128 GB unified memory**, ~273 GB/s memory bandwidth. Capacity is not the constraint; bandwidth is. Prefer FP8 / int8 / GGUF-Q8 and few-step models. Never load bf16 when a quantized variant exists.
- All models and software arrive on a USB flash drive (see `MANIFEST.md` on the drive). **First action on the box: copy everything to local NVMe.** Never run models off the USB drive.
- x86 wheels will not install. Use the aarch64 wheelhouse on the drive: `pip install --no-index --find-links <nvme>/wheels ...`.
- Judging favors business / corporate use cases.

## 2. The product (one line for the pitch)

**An on-prem video production agent for corporate marketing: it turns existing footage and photos into new brand-safe shots — new angles, new scenes with approved spokespeople — and guarantees only consented people appear, with nothing leaving the building.**

The memorable feature is the **consent registry**: every person detected in footage is approved / unknown / remove, and generated output is re-checked so unapproved faces never ship.

Long-term vision (not for today): a professional, UI-first AI video editor, open source, multi-project, with an agent that drives the editor through an API, a model manager that loads models on demand, and a memory layer (characters, scenes, project history).

## 3. Architecture

```
Browser (editor UI)  ──ws/http──▶  FastAPI backend (on the box)
                                     ├─ agent loop (tool calling → local LLM via Ollama)
                                     ├─ model manager (registry.json, memory budget, lazy load/evict)
                                     ├─ job queue → ComfyUI HTTP API (/prompt, /history, /free)
                                     ├─ memory layer (SQLite + sqlite-vec)
                                     ├─ ingest + cast pipeline (scene detect, SAM2, InsightFace)
                                     └─ render (ffmpeg from timeline JSON)
```

### 3.1 Frontend
- Plan A: fork **OpenCut** (MIT, Next.js, already has media bin / multi-track timeline / preview / keyframes). Time-box 1 hour to get it running; ignore its in-progress export and render on the backend.
- Plan B (if OpenCut fights back): minimal custom React editor — media bin, one video track, preview, panels. Fully under our control.
- Panels to add either way:
  - **AI panel**: chat + proposal cards (preview / apply / discard), aware of current selection and playhead.
  - **Cast panel**: detected people with approved / unknown / remove.
  - **Models panel**: each model with status (idle / loading / resident), memory bar, pin toggle, draft/hero tier.
  - **Generative clip type**: a clip that carries its job id, model, references, prompt, seed; shows progress on the timeline; lands in the bin when done; supports "regenerate" in place.
- The browser is only a display. Run it on the box if a monitor exists, else on the laptop over the USB-C link. All compute stays on the box.

### 3.2 Agent
- Hand-written tool-calling loop (~150 lines), OpenAI-compatible chat completions against **Ollama** serving `qwen3-vl:30b` (Qwen3-VL-30B-A3B: MoE, 3B active, vision + tool calling). One model talks and sees frames/contact sheets. Fallback: `Qwen3-VL-8B-Instruct`.
- Permission tiers by reversibility and cost, not by feature:
  1. **Act directly**: Q&A, search, transcription, logging, scene detection, markers, selects.
  2. **Propose, human applies**: assembly, re-timing, swapping shots, effects, masks — built on a proposal track/version.
  3. **Plan → approve → run**: generative and expensive jobs. Agent shows references, model, camera path, estimated time; runs on approval; results land in the bin as candidates, never directly in the cut.
- Every agent action goes through the same command layer as the UI: logged, attributed, undoable.
- Tools to expose (names are suggestions; keep them flat and JSON-schema'd):
  `ingest_footage`, `list_cast`, `set_cast_policy`, `search_memory`, `list_models`, `load_model`, `unload_model`, `model_status`, `generate_keyframe`, `generate_shot`, `reangle_shot`, `remove_person`, `replace_person`, `enforce_cast_policy`, `upscale`, `interpolate`, `add_to_timeline`, `render`, `job_status`.

### 3.3 Model manager
- `registry.json` entries: `id`, `task` (t2i | edit | multiref | t2v | i2v | v2v-reangle | inpaint | animate | segment | face-id | depth | embed | upscale-image | upscale-video | interpolate), `path`, `precision`, `approx_gb`, `load_seconds`, `license`, `tier` (draft | hero), `best_for` (one line the agent reads), `workflow_template`.
- Memory budget (unified, all FP8): LLM ≈ 18–30 GB, ComfyUI cap ≈ 70 GB, analysis models ≈ 5–10 GB.
- Lazy-load on first request; ComfyUI loads on use and `POST /free` unloads; LRU eviction over budget; user/agent can pin. Keep draft-tier models resident; hero pipeline runs sequentially (keyframe model → evict → video model). NVMe swap of a 50 GB model is 15–30 s.
- Expose the same registry to the agent (`list_models(task)`) and the Models panel.

### 3.4 Memory layer
- SQLite + sqlite-vec. Tables: `projects`, `media`, `shots`, `people` (cluster id, role, policy, face embeddings, reference crops, wardrobe crops), `scenes` (environment refs, lighting notes), `generations` (job, model, prompt, seed, refs, parent asset, output), `notes` (free-text project memory, text-embedded).
- Embeddings: InsightFace `buffalo_l` (faces), SigLIP2 (visual search over frames/refs), nomic-embed-text (transcripts, notes).
- Reference pipeline (this is what `ingest_footage` does): PySceneDetect → SAM2 person tracking → face detection + embedding per track → cluster identities across footage **and** still photos → pick best frames (sharp, frontal, well-lit) → crop face / full-body / wardrobe refs → write to `people` + contact sheet → ask human to name/approve.

### 3.5 Background-character rule
- Only people in the cast registry with policy `approved` may appear, foreground or background. Unknown faces in source footage: ask the human (approve / remove). Unknown faces in generated output: `enforce_cast_policy` re-runs face ID on output; on a hit, inpaint out (VACE / Fun Inpaint) or regenerate with a stronger "no other people" prompt. Extras that must stay consistent get their own registry entry with role `background`.

### 3.6 Pipeline stages
`analyze → references → keyframe (image model, multi-ref) → video (i2v / v2v / animate) → policy check → finalize (upscale → interpolate → grain/grade match to project) → timeline`

Generate at 480–720p for speed; upscale only approved takes. Sub-480p cannot become real 4K; keep the generation floor at 720p for anything destined for the timeline.

## 4. Models (paths follow the USB layout: `hf/<org>/<repo>` and `comfyui_models/<type>/`)

**Do not look for Wan 2.7 — it is not open-weights. Official Wan open weights stop at Wan 2.2.**

| Tier | Purpose | Model |
|---|---|---|
| brain | agent + vision | Ollama `qwen3-vl:30b`; HF `Qwen/Qwen3-VL-30B-A3B-Instruct`; fallback `Qwen/Qwen3-VL-8B-Instruct` |
| draft | keyframes, edit, multi-ref | `FLUX.2-klein-4B` (4-step) |
| draft | text/image → video 720p | `wan2.2_ti2v_5B_fp16` + `wan2.2_vae` + `umt5_xxl_fp8_e4m3fn_scaled` |
| draft | reference-to-video, inpaint, edit | `wan2.1_vace_1.3B_fp16` + `wan_2.1_vae` |
| draft | re-angle | `ReCamMaster-Wan2.1` (+ `wan2.1_t2v_1.3B`); fallback Depth-Anything parallax warp |
| hero | image-to-video | `wan2.2_i2v_high/low_noise_14B_fp8_scaled` + `Wan2.2-Lightning` 4-step LoRAs |
| hero | text-to-video | `wan2.2_t2v_high/low_noise_14B_fp8_scaled` + Lightning LoRAs |
| hero | character animate / replace person | `wan2.2_animate_14B` (int8/fp8) |
| hero | camera-controlled re-angle | `wan2.2_fun_camera_high/low_noise_14B_fp8_scaled` |
| hero | bystander removal | `wan2.2_fun_inpaint_high/low_noise_14B_fp8_scaled` |
| hero | keyframes, up to 10 refs, 4 MP | `FLUX.2-dev` fp8 + fp8 text encoder + VAE (non-commercial license — fine today, flag for product) |
| hero | Apache-licensed image gen+edit | `Qwen-Image 2.0` (or `Qwen-Image-Edit-2511`) |
| analysis | segment + track | `sam2.1-hiera-large` / `-small` |
| analysis | face ID | InsightFace `buffalo_l` |
| analysis | depth | `Depth-Anything-V2-Small-hf` / `-Base-hf` |
| analysis | embeddings | `siglip2-base-patch16-224`, `nomic-embed-text-v1.5` |
| analysis | speech (optional) | `whisper-large-v3-turbo` |
| finalize | video upscale | `SeedVR2-3B` (fast) / `SeedVR2-7B` (quality), chunk 33–65 frames with overlap |
| finalize | image upscale / fallback | `4x-UltraSharp`, `RealESRGAN_x2plus` (video, 2x only), `RealESRGAN_x4plus` |
| finalize | frame interpolation | RIFE 4.9 |

Rough hero timings on GB10: 3–6 min per 720p 5 s clip with Lightning LoRAs, 15+ min without. Run a "bakery" queue all afternoon producing hero versions of the demo shots; generate live with draft models during the pitch.

## 5. ComfyUI as the execution backend
- Custom nodes on the drive: `ComfyUI-WanVideoWrapper`, `ComfyUI-segment-anything-2`, `ComfyUI-KJNodes`, `ComfyUI-VideoHelperSuite`, `ComfyUI-SeedVR2_VideoUpscaler`, `ComfyUI-Frame-Interpolation`.
- Build each pipeline as a saved workflow JSON (API format) in `workflows/`. The backend fills parameters and `POST /prompt`, polls `/history/<id>`, fetches outputs. Zero inference code in our repo.
- Templates needed, in order: `klein_keyframe_multiref`, `wan5b_i2v`, `vace_reference`, `vace_inpaint_person`, `recam_reangle`, `wan14b_i2v_lightning`, `seedvr2_upscale`, `rife_interp`, `animate_replace`, `fun_camera_reangle`, `fun_inpaint_person`, `flux2dev_keyframe`.
- **Do not install ComfyUI Manager** (it phones home).

## 6. No-cloud checklist
- `export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`
- Disable Ollama and ComfyUI update checks; no ComfyUI Manager; no analytics in the frontend.
- Verify with a network monitor before the demo.

## 7. Build order for today (checkpoints)
1. Box setup: copy drive → NVMe, venv from wheelhouse, ComfyUI + nodes running, Ollama serving `qwen3-vl:30b`. Smoke-test one klein image and one Wan 5B clip through the HTTP API.
2. Backend skeleton: FastAPI, websocket progress, job queue, ComfyUI client, `registry.json` generated from `MANIFEST.md`, model manager.
3. `ingest_footage` → cast registry → Cast panel data (this is the memory layer and reference pipeline).
4. Agent loop + tools; chat works end-to-end against the backend.
5. `generate_shot` (klein keyframe → Wan 5B) with proposal flow; `enforce_cast_policy`.
6. Editor UI (OpenCut or minimal React) wired to backend; generative clip type; Models panel.
7. `reangle_shot`, `remove_person`, `upscale`; start the hero bakery queue.
8. Demo script rehearsed twice.

**Integration checkpoint by early afternoon:** select a clip → ask chat for a new shot → generative clip appears, progresses, lands in the bin.

Team split: one on editor UI, one on backend + model manager + job queue, one on ComfyUI workflow templates, one on ingest/cast pipeline + agent tools.

## 8. Demo flow
1. Drop footage into the watched folder → agent: "3 people found, 2 match approved cast, 1 unknown — approve or remove?"
2. Approve → "Low-angle shot of Dana in the lobby" → agent shows plan (refs, model, time) → approve → generative clip appears on timeline → lands policy-checked.
3. Show a hero-baked version of the same shot and the upscaled finalize.
4. Close on the consent registry: nothing left the building, nobody unapproved appears.

## 9. Conventions
- Python 3.12, type hints, small modules, `ruff` clean. Every tool is idempotent, logged, and returns JSON.
- Every generated asset carries provenance: model id, precision, prompt, seed, references, parent asset, job id.
- Timeline operations are commands with undo. The agent never bypasses the command layer.
- Secrets: none. If something asks for an API key, it is the wrong dependency.

## 10. Suggested repo layout
```
backend/   app.py (FastAPI), agent/ (loop, tools), models/ (registry.json, manager.py), jobs/ (queue, comfy_client.py),
           memory/ (db.py, embeddings.py), ingest/ (scenes.py, track.py, faces.py, refs.py), render/ (ffmpeg.py)
workflows/ *.json ComfyUI API-format templates
frontend/  OpenCut fork or minimal React editor
scripts/   setup_box.sh, smoke_test.py, bakery.py
```

---

# Workflow (applies to every session and every subagent)

## Session Handoff (read first)

`HANDOFF.md` at the project root is the cross-session / cross-compact handoff. Read it once at
session start — it is kept current enough that a single read restores full working context after
a crash, compact, or new session. After every meaningful step (task finished, decision made,
in-flight work changed), update it in place: overwrite stale sections, never append a log. It is
git-tracked. This whole pattern applies for all subagents doing multi-step work too.

## Token Usage Rules

Keep context small. Do not read the whole repo unless necessary. This whole pattern applies for
all subagents too.

Before broad file search or opening many files:

1. Check Graphify outputs first.
2. Use MemPalace only when prior project decisions or past context may matter.
3. Open only the files needed for the current task.
4. Prefer targeted reads over large scans.
5. Summarize findings before continuing to more files.

## Graphify Usage

Use Graphify as the first-pass repo map. This whole pattern applies for all subagents too.

> **Status (2026-08-22): the graph is built** — `graphify-out/graph.json` exists (81 nodes,
> 142 edges, 6 **labeled** communities, extracted from the planning brief in this file).
> Extraction of `docs/PLAN.md`, `docs/ROLES.md`, `docs/api.md`, `README.md`, and
> `backend/models/registry.json` is in flight and will roughly double it. It becomes a code
> map as source lands. **No post-commit hook and no PreToolUse hooks are configured in this
> repo** — rebuild manually with `graphify update .` after significant changes.

Before architecture work, refactors, dependency tracing, or "where is this implemented?" tasks:

- Orient once per unfamiliar area: read only `## God Nodes` and `## Suggested Questions` from
  `graphify-out/GRAPH_REPORT.md`. Both carry real node labels, which is the vocabulary queries
  need. The communities here ARE labeled (e.g. "Model Manager and Box Setup", "Agent, Consent
  Registry and Editor UI"), so `## Communities` is also usable for navigation.
- Then `graphify query "<question>"` using vocabulary from that orientation, not from the user's
  phrasing. `graphify path "<A>" "<B>"` and `graphify explain "<concept>"` take exact labels.
- Sanity-check every query: if the `Start:` node list is unrelated to your question, the query
  missed — re-query with different labels rather than trusting the subgraph or falling back
  to grep.
- Read the full report only for broad architecture review.
- Fall back to broad search only when the graph is missing or stale.

**Why this order:** `graphify query` is fuzzy label-matching, so it fails *silently* when your
phrasing doesn't match node labels — it returns a confidently-wrong subgraph with no error. The
orientation sections are what make queries hit; the full report is a summary, not a dump, so
reading it is cheap — it is just untargeted.

## MemPalace Usage

Use MemPalace for long-term project memory. This whole pattern applies for all subagents too.

Use it when:

- the user says we discussed something before
- prior architecture decisions matter
- the current task depends on earlier reasoning
- you need to recall previous plans, conventions, or implementation choices

Do not use MemPalace for every task. Do not treat recalled memory as automatically true. Verify
against the current repo when needed.

This project's palace: wing `dell_hardware_hack`, stored at `.mempalace/palace` (project-local —
the global `MEMPALACE_PALACE_PATH` is a *relative* path, so always run `mempalace` commands from
the project root). Search with `mempalace search "<question>"` (CLI) or the `mempalace_search`
MCP tool. Refile after doc changes with `mempalace mine .`.

### Revive MemPalace after every compact

The MemPalace MCP server (stdio) drops silently across long sessions and every `/compact`
boundary — its `mcp__plugin_mempalace_mempalace__*` tools then show as disconnected (no error,
no data loss). **After every `/compact`, before relying on MemPalace, verify its tools are
connected; if they are not, prompt the user to run `/plugin` (or `/mcp`) to revive it** (the
agent cannot invoke those slash-commands itself). Until it is reconnected, fall back to the file
memory + Graphify.

## File Memory

The third memory layer, independent of MemPalace and always loaded — the per-project memory
directory. The key is derived from the project path, so it differs by machine:

- host Mac: `~/.claude/projects/-Users-wally-Documents-GitHub-dell-hardware-hack/memory/`
- any Codespace: `~/.claude/projects/-workspaces-dell-hardware-hack/memory/`

`MEMORY.md` there is the index loaded into every session. Write a memory when a fact is durable
and not derivable from the code or git history — project goals, constraints, decisions with a
rationale, or user preferences about how work should be done. One fact per file, indexed in
`MEMORY.md`. Do not record what the repo already says. Renaming the project directory orphans
this store until retagged.

## Working Style

For implementation tasks (this whole pattern applies for all subagents too):

1. Identify the smallest relevant file set.
2. Explain the intended change briefly.
3. Make focused edits.
4. Run or suggest the narrowest useful test.
5. Avoid unnecessary rewrites.

For design tasks: use Graphify for repo structure, MemPalace for past decisions only if
relevant, and keep the answer concise and action-oriented.

## Orchestrator Mode

For EVERY assignment: act as the orchestrator, not the implementer. **Parallelism is the point —
today is a one-day build, and wall-clock time is the scarcest resource.**

1. Break the assignment down into individual parts.
2. Hand each part off to subagents — **background and parallel wherever parts are independent**;
   give each a self-contained prompt with exact specs and a required report format.
3. Keep only the glue: integrate the subagents' outputs, resolve conflicts between them, and do
   the final wiring.
4. Verify everything works end-to-end yourself before reporting done — run the checks, curl the
   endpoints, read the diffs; never relay a subagent's "done" unverified.

Do a part yourself only when it is trivially small (a small or one-line edit, single command),
when it IS the glue/verification, or when the user explicitly says to do it yourself.

## Conductor Rule

The main loop is the CONDUCTOR. It is imperative that its context window stays SMALL.

1. Edit files yourself ONLY for small / one-line changes.
2. Anything that requires complex reasoning — design work, multi-file edits, debugging, asset
   builds, deep analysis — is handed off to a subagent with a self-contained spec.
3. The conductor keeps only: spec-writing, dispatch, integration/glue, conflict resolution, and
   end-to-end verification of subagent output.
4. Protect the context window: consume subagent REPORTS instead of raw files; never pull large
   files, transcripts, or logs into the conductor's context when a subagent can read them and
   return a summary.

**Branch discipline for subagents:** a subagent writes only inside the directories its role owns
(see `docs/ROLES.md`). Two subagents must never be given overlapping write territories. The
conductor commits; subagents do not run `git commit` or `git push` unless the spec says so.

## Derived Artifacts

`graphify-out/`, `.mempalace/`, `mempalace.yaml`, and `entities.json` are gitignored and
machine-local. They are rebuilt, never hand-edited:

- `graphify update .` rebuilds the graph (manual — no hook in this repo).
- `mempalace mine .` refiles project files into the palace.

## Project Rule

Optimize for low-token, high-signal work. Prefer precise context retrieval over loading large
files or repeating architecture summaries.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and
cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json
  exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"`
  for focused concepts. These return a scoped subgraph, usually much smaller than
  GRAPH_REPORT.md or raw grep output.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when
  query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API
  cost).
