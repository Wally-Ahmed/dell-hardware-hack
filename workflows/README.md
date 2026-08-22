# workflows/ — ComfyUI API-format templates

**This directory is Role A territory.** The backend fills these templates and posts them to
ComfyUI; zero inference code lives in the repo. Until real templates land here, the backend
runs with `RUSHCUT_EXECUTOR=simulated` and fakes generation.

## Required templates (priority order — the first two are the live demo loop)

| File | Purpose | Models involved |
|---|---|---|
| `klein_keyframe_multiref.json` | Draft keyframe from refs | FLUX.2-klein-4B |
| `wan5b_i2v.json` | Draft image→video 720p | Wan2.2-TI2V-5B |
| `vace_inpaint_person.json` | Person removal (consent beat) | Wan2.1-VACE-1.3B |
| `seedvr2_upscale.json` | Finish/upscale approved takes | SeedVR2-3B |
| `wan14b_i2v_lightning.json` | Hero i2v (bakery) | Wan2.2-I2V-14B + Lightning LoRA |

## How to create one (on the box)

1. Open ComfyUI at `http://localhost:8188`, build the graph, run it once to confirm.
2. **Rename the input nodes** the backend must control (right-click → Title):
   - `RUSHCUT_PROMPT` — the positive-prompt text node
   - `RUSHCUT_SEED` — the sampler/seed node
   - `RUSHCUT_IMAGE` — the image-load node (refs / source frame)
   The backend patches ONLY nodes with these exact titles (`backend/jobs/executor.py`,
   `patch_workflow()`); everything else in the graph is yours.
3. Enable dev mode (settings) → **Save (API format)** → save as the exact filename above,
   into this directory.
4. Commit on branch `box` and push (or hand to a teammate). Re-run
   `python3 scripts/smoke_test.py` — check C goes green once `wan5b_i2v.json` exists.

A worked example of the patching convention lives at
`backend/tests/fixtures/wan_fixture.json`.
