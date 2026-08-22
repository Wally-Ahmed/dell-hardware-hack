# Role A — Box & Models: Onboarding Packet

**You are the most important person on this team tonight.** Everything the rest of us build
targets the machine in front of you, and none of us can touch it — Claude (the AI running the
core build) has no access to the box, ever. You are its hands. This document is for you AND
for the AI agent on your laptop.

> **If you are an AI agent reading this:** treat this file as your primary context. Your
> human is Role A on a one-day hackathon (demo TONIGHT, ~6–7 PM EDT, 22 Aug 2026). After
> reading this, read — in order — `HANDOFF.md`, `docs/ROLES.md`, `scripts/BOX_RUNBOOK.md`,
> and `CLAUDE.md` §1/§5/§6, all in this repo. Hard rules for you are at the bottom of this
> file. Do not improvise around them.

---

## The mission, in six lines

We are building an AI-native video editor for professional filmmakers. An agent edits
alongside the human and generates new footage with local diffusion models. The signature
feature is a **consent registry**: nobody unapproved ever appears in a shot, real or
generated. Everything runs on ONE machine — a Dell Pro Max with an NVIDIA GB10 (aarch64
Ubuntu, 128 GB unified memory). **No cloud, no telemetry — judges may literally watch the
network during the demo.** Your job: make that machine run models, prove it with a smoke
test, then keep a background queue of "hero" clips baking all afternoon.

## What you need (requirements)

| # | Requirement | Why |
|---|---|---|
| 1 | The GB10 box, powered, with keyboard | The target. Everything runs here. |
| 2 | **A monitor OR a 4K HDMI dummy plug** | The GPU produces NO framebuffer without a detected display. Without this, mysterious failures. |
| 3 | The USB flash drive (has `MANIFEST.md`) | All models + software arrive on it. |
| 4 | Your laptop, on network, with team chat | You paste box output to us; Claude debugs through you. |
| 5 | Git clone of this repo ON the box | `git clone https://github.com/Wally-Ahmed/dell-hardware-hack` — do this EARLY, while the box still has network. |
| 6 | (Side quest) Phone/camera + 2–3 teammates who consent | Demo footage + stills. The consent registry needs real people who said yes. |
| 7 | **A power strip**, and every model on external storage BEFORE arriving | Venue outlets and venue wifi are both scarce. `scripts/DOWNLOADS.md` is the shopping list — pull Tier 1 on a fast pipe at home. |

**Timing reality:** hero clips take 3–6 minutes EACH on this hardware (it is 2.75–4.7×
slower than a desktop 5090). The bakery queue needs every minute — target: **smoke test
green and bakery running as early as physically possible.**

---

## Visual checklist

```
PHASE 0 — ARRIVE                                           target: now
  [ ] Box powered, monitor or HDMI dummy plug attached
  [ ] USB drive plugged in
  [ ] Repo cloned onto the box (while network exists)
  [ ] Team chat open on laptop

PHASE 1 — COPY                                             ~20–40 min (mostly waiting)
  [ ] rsync USB → NVMe started        (BOX_RUNBOOK §2 — never run models off USB)
  [ ] While it copies → start PHASE S side quests below

PHASE 2 — SETUP                                            ~15 min
  [ ] bash scripts/setup_box.sh /path/to/nvme/root
  [ ] ComfyUI answering on :8188         (script waits for it)
  [ ] Ollama serving qwen3-vl:30b on :11434
  [ ] Backend up on :8000  (RUSHCUT_EXECUTOR=comfy)
  [ ] ComfyUI-Manager NOT installed      (script checks — it phones home)

PHASE 3 — SMOKE TEST  ★ GO/NO-GO FOR THE ENTIRE DEMO ★     ~15 min
  [ ] python3 scripts/smoke_test.py
  [ ] a) ComfyUI alive   b) brain replies BOX-OK   c) one real generation
  [ ] PASTE THE FULL OUTPUT INTO TEAM CHAT  ← do not skip, green or red

PHASE 4 — WORKFLOW TEMPLATES                               ~45 min
  [ ] klein_keyframe_multiref.json   → workflows/   (BOX_RUNBOOK §5, GUI → "Save (API format)")
  [ ] wan5b_i2v.json                 → workflows/   (these two = the live demo loop)
  [ ] vace_inpaint_person.json       → workflows/   (the consent-enforcement beat)
  [ ] seedvr2_upscale.json           → workflows/   (the finish)
  [ ] git add workflows/ + commit on branch `box` + push (or hand to a teammate to push)

PHASE 5 — HERO BAKERY  ★ START ASAP — EVERY MINUTE COUNTS ★
  [ ] python3 scripts/bakery.py --list     (review the queue)
  [ ] python3 scripts/bakery.py --run      (leave it running ALL afternoon)
  [ ] Check on it every ~30 min; it is resumable after Ctrl-C or crash

PHASE 6 — LOCKDOWN (before judges, ~1 hr before demo)
  [ ] HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, HF_HUB_DISABLE_TELEMETRY=1  (script set these)
  [ ] Ollama + ComfyUI update checks disabled; no frontend analytics
  [ ] Network monitor running → confirm SILENCE          (BOX_RUNBOOK §7)
  [ ] Box network dark; demo runs entirely local

PHASE S — SIDE QUESTS (during any waiting)
  [ ] Film 2–4 short clips of consenting teammates (walking, talking, a lobby/hallway scene)
  [ ] 2–3 clear photos of each consenting person (frontal, good light)  → one named folder
  [ ] One clip that includes a person who will play "unapproved" (with their OK — they get
      detected and removed on stage; that IS the demo's best moment)
  [ ] Projector/display for the pitch tested at its real resolution
```

---

## How we work together (communication protocol)

1. **You paste, Claude fixes.** Any error, any weird output → paste the exact text into team
   chat. Claude (running the core build) reads it and replies with the exact next command.
   Never spend more than ~10 minutes stuck silently.
2. **The smoke test output goes in chat no matter what.** Green = the whole team switches
   from mock to real backend. Red = we triage immediately. Silence is the only wrong move.
3. **Commit on branch `box`.** Your territory is `workflows/` and `scripts/`. Nobody else
   writes there; you don't write anywhere else. If the box can't push (network down), copy
   files to your laptop via USB and push from there, or hand them to any teammate.
4. **Decisions are already made.** Model choices, precisions, flags — all written down.
   If something contradicts the docs, say so in chat; don't re-decide on the box.

## The gotchas (each one costs an hour if you hit it blind)

| Symptom | Cause | Fix |
|---|---|---|
| ComfyUI OOMs at ~half the RAM the box has | Unified-memory double-allocation bug (mmap copy) | Run with `--disable-mmap` (setup script does) and budget 2× model size at load |
| Everything runs ~10× slower than expected | ONNX Runtime has no aarch64 wheel → preprocessors silently on CPU | Known; avoid DWPose/ControlNet paths tonight, or ask Claude in chat |
| GPU "not doing anything", black/no output | No display detected → no framebuffer | Attach monitor or the 4K HDMI dummy plug |
| Video gen not faster in NVFP4 | NVFP4 is weight-only; video DiTs are compute-bound | Use **FP8 for diffusion**, NVFP4 only for the LLM |
| The brain (LLM) is painfully slow | Dense model = bandwidth wall (~10 tok/s) | Use the MoE default `qwen3-vl:30b` (~85+ tok/s) |
| Something phones home during the demo | ComfyUI Manager / update checks / HF telemetry | Never install Manager; setup script sets all env kill-switches; verify with the monitor |
| A tool wants an API key | Wrong dependency — this product has NO cloud | Stop, say so in chat. Secrets: none, ever. |

---

## For the AI agent assisting Role A — hard rules

You run on Role A's **laptop** (or on the box during the afternoon only). Priorities and
constraints, in order:

1. **The demo is tonight.** Optimize for "smoke test green, bakery running", not elegance.
   The cut-line and the clock live in `docs/ROLES.md` — respect both.
2. **The box goes fully offline before the demo** and stays offline. You (a cloud-backed
   agent) must therefore be OFF the box by lockdown; before that, prefer running on the
   laptop and giving your human commands to type/paste.
3. **Never** install ComfyUI-Manager, never run ComfyUI with `--gpu-only`, never load a bf16
   model when a quantized variant exists, never touch files outside `workflows/` and
   `scripts/`, never commit to any branch except `box`, never introduce anything that needs
   an API key.
4. The scripts in `scripts/` are the source of truth for setup. Read them before inventing
   commands. `backend/models/registry.json` is the source of truth for model paths, tiers,
   and precisions — model files live under the NVMe root per `MANIFEST.md` on the USB drive.
5. Workflow templates use a node-title convention: nodes titled `RUSHCUT_PROMPT`,
   `RUSHCUT_SEED`, `RUSHCUT_IMAGE` are the inputs the backend patches. Templates are saved
   from the ComfyUI GUI via **Save (API format)** into `workflows/<name>.json` with exactly
   these names: `klein_keyframe_multiref`, `wan5b_i2v`, `vace_inpaint_person`,
   `seedvr2_upscale`.
6. When anything fails, produce for your human a SHORT paste-ready block for team chat:
   what was run, exact error, your one-line hypothesis. The conductor session (Claude, with
   full project context) debugs cross-component issues — don't burn an hour going deep solo.
7. Consent matters for real here: only film/photograph teammates who explicitly agree, note
   who agreed in the footage folder (`CONSENT.txt`: name + "agreed to appear in demo"), and
   never push footage of real people to the public repo (the `.gitignore` blocks media —
   keep it that way).
8. Context you do NOT have: the backend/agent internals, the editor fork, the research
   record. You don't need them. If your human is asked to do something outside `workflows/`
   + `scripts/` + footage, redirect it to team chat.

**Glossary for the agent:** "draft tier" = small/fast models used live on stage (klein-4B,
Wan 5B). "Hero tier" = 14B models with Lightning LoRAs, 3–6 min per 5 s clip, pre-baked by
`bakery.py`. "Smoke test" = `scripts/smoke_test.py`, the go/no-go. "The conductor" = the
Claude session coordinating all roles. "Air-gap" = box network silent, provable with a
monitor.

---

*Written by the conductor session, 22 Aug 2026. If this file and reality disagree, say so
in team chat — reality wins, then we fix the file.*
