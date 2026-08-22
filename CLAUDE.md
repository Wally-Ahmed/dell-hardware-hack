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
