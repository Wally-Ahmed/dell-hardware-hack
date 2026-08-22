# Roles & Branches

**Read this first, then `docs/api.md`, then start.** Full reasoning lives in `docs/PLAN.md`.

Everything ships tonight. The rule that makes five people fast instead of five people
merging: **you own directories, not features.** Two people are structurally incapable
of editing the same file.

## Before anyone branches

The **contract commit** lands on `main` first — `docs/api.md`, `backend/models/registry.json`,
the MongoDB collection shapes, the job-state enum, and a mock FastAPI server returning canned
job results. Nobody edits those files after 13:30 without agreement from roles B, C, and D.

Branch from that commit. Not before it.

## The five roles

| Role | Branch | Owns exclusively | First deliverable |
|---|---|---|---|
| **A — Box & Models** | `box` | `workflows/`, `scripts/`, the GB10 itself | Klein image + Wan 5B clip through the ComfyUI HTTP API |
| **B — Backend & Jobs** | `backend` | `backend/app.py`, `backend/jobs/`, `backend/models/`, `backend/render/` | Job queue + WebSocket progress against the mock |
| **C — Editor UI** | `editor` | `frontend/` (all of it) | Fork building, timeline rendering, four panels stubbed |
| **D — Ingest & Cast** | `ingest` | `backend/ingest/`, `backend/db/` | MongoDB collections + person clustering on one clip |
| **E — Agent & NemoClaw** | `agent` | `backend/agent/`, `nemoclaw/` | NemoClaw sandbox reaching the backend, one tool round-trip |

**Fewer than five people?** With four, E folds into B. With three, D absorbs E and C takes
the render path.

**Role A works on the GB10 directly**, not in a Codespace — their job *is* the box.
Everyone else works in their own Codespace (per-user, so four dev servers, no port collisions).

## Merge protocol

Merges to `main` happen **on a clock: 14:30, 15:30, 16:30.** Not when you feel ready.

- Short-lived branches merged often is the entire point. A branch that lives six hours is a
  fork with extra steps.
- Each merge is a fast-forward or a small rebase.
- Whoever breaks `main` fixes it immediately rather than continuing on their branch.
- Nobody force-pushes `main`.
- Need something outside your territory? **Ask the owner.** A thirty-second conversation
  beats a merge conflict at 17:00.

```bash
git checkout <your-branch>
git fetch origin && git rebase origin/main   # before every merge window
git push origin <your-branch>
# then merge to main, or open a PR if you prefer the paper trail
```

## The one cross-cutting seam

The **generative clip** touches the editor (rendering + progress), the backend (job lifecycle),
and ingest (policy check on completion). Its contract — the exact JSON shape of a job and its
state transitions — is in `docs/api.md` and changes only by agreement between B, C, and D.

Name it now so nobody discovers it at 16:00.

## Clock

| Time | What |
|---|---|
| 13:30 | Contract commit on `main`. Branch after this. |
| 14:15 | Role C commits to an editor base (OpenCut vs OpenChatCut bake-off). No revisiting. |
| **14:30** | **Hero bakery starts.** Non-negotiable — this hardware is 2.75–4.7× slower than a 5090. |
| 14:30 | Merge window 1 |
| **15:30** | **Integration checkpoint.** Clip → chat → generative clip on timeline, policy-checked. If this isn't working, stop adding features and defend it. |
| 15:30 | Merge window 2 |
| 16:30 | Merge window 3 |
| 16:00+ | Smoke test green, then rehearse twice on the real box |

## Cut line

**Ship:** editor, chat panel, agent loop, one image pipeline, one video pipeline, cast panel,
generative clip, `enforce_cast_policy`.

**Cut in this order if needed:** OTIO export → NemoClaw sandbox (fall back to direct Ollama
loop) → live bakery (show pre-baked) → `reangle_shot` → `remove_person` → Models panel polish.

Nothing above the line is sacrificed to save something below it. Whoever notices we're behind
says so at 15:30, not 17:30.

## Gotchas that will each cost you an hour

**Role A, before you start:**
- ComfyUI has a unified-memory double-allocation bug on this hardware — safetensors get mmap'd
  into RAM then copied into "VRAM" which is the same RAM, effectively halving usable memory to
  ~64 GB. Run with `--disable-mmap` and budget 2× model size at load.
- Pass `--disable-api-nodes` to force fully offline operation.
- ONNX Runtime has no aarch64 wheel on PyPI — DWPose/ControlNet preprocessors silently fall
  back to CPU and look like a mysterious 10× slowdown.
- Never use `--gpu-only`; it fights the unified-memory fabric.
- Do **not** install ComfyUI Manager. It phones home.
- Set `HF_HUB_DISABLE_TELEMETRY=1` alongside `HF_HUB_OFFLINE=1` — HF fires telemetry on
  downloads independently of ComfyUI.
- The GB10's GPU only produces a display framebuffer when a monitor is detected. Bring a real
  display or a 4K HDMI dummy plug.
- Use FP8 for diffusion, NVFP4 for the LLM. NVFP4 does *not* speed up video diffusion here —
  it's weight-only and video transformers are compute-bound.

**Role D, license flags (fine tonight, must change before release):**
- InsightFace's *pretrained models* are non-commercial research only (the code is MIT, the
  weights are not). AdaFace (MIT) is the drop-in replacement.
- Ultralytics YOLO is AGPL. RT-DETR (Apache-2.0) is the replacement.
- ProPainter and MatAnyone are strictly non-commercial. Netflix VOID (Apache-2.0) and Wan VACE
  inpaint are the permissive removal options.

**Role E:**
- Time-box the NemoClaw integration to 90 minutes. It's early-preview. The fallback is a
  hand-written ~150-line tool loop straight against Ollama — loses the sandbox demo, not the
  product.
- Cap the tool count at 20–30. Measured: tool-selection accuracy collapses from ~95% to ~71%
  when a large toolset is loaded.
- Reference clips by **stable id, never ordinal position**. "The third clip" drifts.
- Never expose `execute_arbitrary_code`.
