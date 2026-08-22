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

## ALL SOFTWARE LANES DONE — main `83eb544`, 55/55 suite, ruff clean

Every branch at the same tip. What remains is the BOX (human + hardware) and the demo.

**19:35 EDT regression status:** ten commits landed after the original core-loop drive
(pre-GPU cast gate, per-job-type template mapping, runsheet, walkthrough v2–v4). Suite
re-verified green on tip in the Codespace (43/43 backend+agent+ingest there); a fresh
full-loop UI drive on tip is running. **Box-side evidence (smoke test, LOOP GREEN ON REAL
WEIGHTS) has NOT been pasted to the conductor yet** — Role A has the runsheet
(docs/DEMO_RUNSHEET.md) and the endgame prompt (docs/ENDGAME_PROMPT.md); the two gating
pastes remain: smoke output, then the loop-check result. On green, flip
`RUSHCUT_EXECUTOR=comfy` re-verification is Role A-side (the conductor cannot reach the
air-gapped box; it debugs through pasted output).

- **Core loop PROVEN end to end in the Codespace** (editor + real backend + dev brain):
  pendingPlan held with ZERO jobs → approve → `generate_shot` → complete, clear verdict,
  provenance; policy beat: `policy_blocked` present. Panels serve `ai-chat-panel` /
  `cast-panel` / `models-panel` testids on `/rushcut-dev` (the editor page SSRs a loading
  gate by design — panels live in its chunk, hydration verified headless + reproduced by
  the conductor). Typecheck: zero new errors (12 pre-existing, identical set).
- **Editor (Role C, `ad267dc`)** — 4 panels, GenerativeElement with live WS progress fill
  and policy tint, zustand WS store, `/rushcut-dev` harness. `bun run dev` in
  `frontend/apps/web` (needs `.env.local`; `NEXT_PUBLIC_BACKEND_URL` default :8000).
- **Render** (`6b3e897`) — /render verified with real encodes (2 clips + 500 ms gap →
  exactly 2500 ms). Rendered files now carry a provenance `comment` tag (ffprobe-verified).
- **Ingest & cast (Role D)** (`06a7a33`) — repo-backed /people, clustering (unresolved
  NEVER dropped), `RUSHCUT_ANALYZERS=real|fake`. Live e2e = the demo beat.
- **Pre-GPU cast gate** (`a2505c7`, peer-review idea) — jobs referencing non-approved or
  unregistered people are born `policy_blocked`; the GPU never runs. Live-verified fresh
  process (a seeding-order bug was caught live and regression-tested).

## Peer-repo review (rmcmurrer81/videostudio) — outcomes

Incorporated as reimplemented ideas: pre-GPU gate, provenance-in-file metadata,
NVIDIA dgx-spark-playbooks pointer in `workflows/README.md` (Apache-2.0, GB10-validated
fallback graphs — fetch from NVIDIA upstream, license-clean). Their repo has NO license:
no code copied. Stretch ideas parked: ffmpeg auto color-match, relight presets, Mongo
checkpoint/restore demo beat. **OPEN QUESTION for the user:** their HACKATHON_RULES.md
quotes an organizer email requiring stack "NemoClaw + OpenClaw + OpenShell" (we comply)
AND planning model `nvidia/Qwen3.6-35B-A3B-NVFP4` via vLLM **on port 8000** (collides with
our backend port; differs from our Ollama brain). Verify against the real email; both are
env-level flips at the box (`RUSHCUT_OLLAMA_URL`, `NEXT_PUBLIC_BACKEND_URL` + `--port`).

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
