# HANDOFF — read once at session start, keep current

*Updated 2026-08-22 ~14:00 EDT by the conductor session. Overwrite stale sections in place;
never append a log.*

## Where we are

Demo is **this evening**. Repo is public: https://github.com/Wally-Ahmed/dell-hardware-hack
(GPL-3). `main` carries the contract; five role branches exist: `box`, `backend`, `editor`,
`ingest`, `agent`. See `docs/ROLES.md` for ownership and the clock, `docs/api.md` for the
contract, `docs/PLAN.md` for the full architecture essay.

## Done and verified

- Contract commit on `main`: `docs/api.md`, `docs/ROLES.md`, `docs/PLAN.md`,
  `backend/models/registry.json` (20 models, licenses verified), devcontainer, GPL-3 LICENSE.
- **Mock backend** `backend/mock/app.py` — verified end to end: jobs walk all six stages over
  ~8 s emitting full-object WebSocket frames; `MOCK_POLICY_HIT=1` forces the `policy_blocked`
  path (unapproved face 0.81 + an unresolved no-face track). Run:
  `uvicorn backend.mock.app:app --port 8000`.
- **Codespace** `nle-main-v6gxg5rp9wprcxpx9` (x86_64, node 20, py 3.12, mongod) — SSH works.
  First codespace was deleted: base image had no sshd; the fix (sshd devcontainer feature) is
  committed, so new Codespaces get it.
- Memory tooling on the host Mac: MemPalace (wing `dell_hardware_hack`), graphify graph of the
  brief (81 nodes / 6 labeled communities), auto-memory entries incl. GB10 gotchas.

## In flight (three parallel builders)

- **Role C** — panels (AI chat / Cast / Models), generative timeline element, WS client in
  the vendored OpenCut; building in the Codespace on `editor`; verified dev-boot required.
- **Role D** — `backend/db` (motor + in-memory fallback), `backend/ingest` (cosine
  clustering, ref selection, pluggable analyzers with fakes, real /people + /ingest
  routers); commits land on `ingest`.
- **Render** — `backend/render` (timeline JSON → ffmpeg trim/concat, router, graceful-skip
  tests).

## Core loop status (goal: demo-ready 17:30)

**Backend half PROVEN live** (commit `1e37623`): dev brain (scripted OpenAI-compatible
stand-in, `backend/agent/dev_brain.py`, port 11434) + real backend + real AgentLoop —
turn 1 held a pendingPlan with ZERO jobs created; approval executed `generate_shot`; job
walked to `complete` with clear verdict + full provenance. `forcePolicyHit` lands
`policy_blocked` (unapproved 0.81 + unresolved no-face + inpaint remediation). The GB10
swaps the brain via `RUSHCUT_OLLAMA_URL` — dev brain never runs there. UI half lands with
Role C, then the loop gets driven through the editor.

**Role A is fully enabled:** `docs/ONBOARD_ROLE_A.md` (handoff packet incl. agent hard
rules), `scripts/` (runbook, setup, smoke test, bakery — all verified), `workflows/README.md`
(template names + RUSHCUT node convention), `docs/DEMO_SCRIPT.md` (four beats + fallbacks).

**Team-chat ask for Role A (post when they exist):** run the runbook; paste smoke-test
output; the moment it's green say so — the conductor flips `RUSHCUT_EXECUTOR=comfy`,
re-verifies the loop, and starts the bakery if you haven't.

- **Waiting on humans:** role claims in `docs/ROLES.md`; `claude` auth in the Codespace;
  GitHub usernames → collaborator access (until then, fork + PR).

## Merged to main and verified (window 1+)

- **Backend (Role B)** — `e328277`: job queue, full state machine incl. `policy_blocked`,
  pluggable executor (`RUSHCUT_EXECUTOR=simulated|comfy`), ComfyUI client with `RUSHCUT_*`
  node-title patching, model manager (70 GB cap, LRU, pin-safe). 18/18 tests **locally and
  in the Codespace**; live job walked queued→complete with provenance.
- **Agent (Role E)** — merged via `034126d`: 18 tools (7 direct / 4 propose / 7 plan),
  ~160-line loop with a real plan-approval gate, router mounted in `app.py` (same HTTP
  contract as the UI, no back door), `nemoclaw/egress-policy.yaml` = the air-gap demo
  artifact. 25/25 combined suite; `/agent/tools` smoke-tested.
- **Editor base (for Role C)** — bake-off verdict: **OpenCut @ `pre-rewrite` (238750c,
  MIT)** over OpenChatCut (node-24 + onnxruntime fights, AGPL, agent runtime welded to its
  own server). Vendored at `frontend/` (`55c1b34`) with `VENDOR.md` naming the three first
  files for our panels. Toolchain: bun; app at `frontend/apps/web`.
- Codespace git note: pushes over `gh codespace ssh` need `bash -lc` (login shell loads
  GITHUB_TOKEN; plain ssh shells fail auth at push time).

## Done since previous update

- **Codespace tooling installed** in `nle-main-v6gxg5rp9wprcxpx9`: claude CLI 2.1.197 with
  Fable-max settings, MemPalace CLI 3.7.1 with a project-local palace (**180 drawers**, rooms
  backend/documentation/general — always pass `--palace .mempalace/palace` in raw SSH shells;
  the env var only applies inside Claude Code), graphify CLI, auto-memory with 2 seed entries.
  **Pending manual step: the user must run `claude` once in the Codespace (interactive auth).**
- **Knowledge graph rebuilt across all docs**: 261 nodes, 434 edges, **12 labeled
  communities** (was 81/142/6 covering CLAUDE.md only). New-doc extraction links into the
  original `claude_*` nodes; rejected alternatives carry their rejection rationale.

## Not started

- Editor fork bake-off (OpenCut vs OpenChatCut) — Role C, time-boxed 30 min, decision by 14:15.
- Ingest/cast pipeline (Role D), agent loop + NemoClaw (Role E, 90-min time-box).
- Everything on the GB10 (Role A): NVMe copy, ComfyUI + nodes, Ollama, smoke test, workflow
  templates, hero bakery (**must start by ~14:30**).

## Decisions that bind

- MongoDB for state; embeddings as plain arrays + numpy cosine tonight (no Atlas-style search
  node on aarch64 today). NemoClaw is the agent harness (Apache-2.0, DGX Spark is a tested
  platform; egress allowlist = the air-gap demo). Say "policy-enforced, audited,
  human-signed-off" — never "guaranteed".
- License flags for release (fine tonight): FLUX.2-dev and InsightFace weights are
  non-commercial → Qwen-Image-Edit-2511 / AdaFace are the swaps. Ultralytics is AGPL → RT-DETR.
- Teammates without collaborator access: fork → PR. Add them as collaborators the moment
  usernames arrive.

## Sharp edges (cost an hour each if forgotten)

GB10: ComfyUI `--disable-mmap` (unified-memory double-alloc bug halves usable RAM),
`--disable-api-nodes`, no ComfyUI Manager, no `--gpu-only`, ONNX has no aarch64 wheel (silent
CPU fallback), FP8 for diffusion / NVFP4 for LLM only, monitor or HDMI dummy plug required,
`HF_HUB_DISABLE_TELEMETRY=1` separate from `HF_HUB_OFFLINE=1`. Diffusion here is 2.75–4.7×
slower than a 5090 — bake heroes early.
