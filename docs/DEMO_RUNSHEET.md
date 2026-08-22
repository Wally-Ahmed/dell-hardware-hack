# Role A — Demo Runsheet: clear everything, then build the demo

**Paste this whole file to the box agent. Human + agent work it top to bottom.**
Every phase starts with a CHECK so it's safe to re-run from wherever you actually are.
Rules recap for the agent at the bottom. When anything blocks >10 min: paste the exact
error to team chat and move on — the conductor debugs through you.

---

## Phase 0 — Where are we? (2 min, paste the result)

```bash
cd ~/dell-hardware-hack 2>/dev/null || git clone https://github.com/Wally-Ahmed/dell-hardware-hack ~/dell-hardware-hack && cd ~/dell-hardware-hack
git pull -q origin main
echo "=== STATUS BLOCK — paste everything below to team chat ==="
echo "arch: $(uname -m) | disk free: $(df -h "${NVME_ROOT:-$HOME}" | tail -1 | awk '{print $4}')"
command -v ollama >/dev/null && ollama list 2>/dev/null | head -4 || echo "ollama: MISSING"
command -v huggingface-cli >/dev/null && echo "hf-cli: ok" || echo "hf-cli: MISSING"
ls "${NVME_ROOT:-/nvme}"/ComfyUI/main.py 2>/dev/null && echo "ComfyUI: present" || echo "ComfyUI: MISSING"
curl -s --max-time 3 localhost:8188/system_stats >/dev/null && echo "ComfyUI: RUNNING" || echo "ComfyUI: not running"
curl -s --max-time 3 localhost:11434/v1/models >/dev/null && echo "Ollama: RUNNING" || echo "Ollama: not running"
curl -s --max-time 3 localhost:8000/health || echo "backend: not running"
ls workflows/*.json 2>/dev/null || echo "templates: none yet"
echo "=== END STATUS BLOCK ==="
```

Whatever this prints decides which phases below you skip. **Paste it either way.**

## Phase 1 — Software + models (SKIP any line already satisfied)

- Software missing (ollama / hf-cli / ComfyUI / torch / bun)? → `scripts/DOWNLOADS.md` **Tier 0**, top to bottom.
- Models missing? → **Tier 1** (brain + Wan 5B stack + klein, ~50 GB), then Tier 2 (~8 GB). Tier 3 only on a fast pipe.
- All of this happens **while the network is up**. If `setup_box.sh` already ran, `unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE` in the download shell.
- Place files per the layout at the bottom of DOWNLOADS.md (`comfyui_models/<type>/`, `hf/`).

## Phase 2 — Bring-up (15 min)

```bash
bash scripts/setup_box.sh "$NVME_ROOT"
python3 scripts/smoke_test.py        # PASTE FULL OUTPUT TO TEAM CHAT — green or red
```
Expected first run: **A PASS, B PASS, C SKIP** (C needs a template — that's Phase 3, not a failure).
Any FAIL → the printed hint, then the runbook's "If something breaks", then paste to chat.

## Phase 3 — The template that makes it real (30–45 min)

Build `wan5b_i2v` in the ComfyUI GUI (`http://localhost:8188`) per `workflows/README.md`:
image→video with Wan2.2-TI2V-5B + wan2.2_vae + umt5 fp8. Then the three renames that
matter — right-click → Title: prompt node → `RUSHCUT_PROMPT`, sampler/seed → `RUSHCUT_SEED`,
image loader → `RUSHCUT_IMAGE`. Settings menu → enable Dev mode → **Save (API format)** →
save as `workflows/wan5b_i2v.json`.

```bash
python3 scripts/smoke_test.py        # C must now go GREEN — a real clip generates. PASTE IT.
git checkout box && git add workflows/ && git commit -m "wan5b_i2v template" && git push origin box
```

If time allows after Phase 5 is moving: same drill for `klein_keyframe_multiref.json`
(keyframes) and `vace_inpaint_person.json` (removal). Hero template
`wan14b_i2v_lightning.json` only if Tier 3 models downloaded.

## Phase 4 — Start the product (10 min)

```bash
cd ~/dell-hardware-hack && source "$NVME_ROOT/venv/bin/activate"
RUSHCUT_EXECUTOR=comfy RUSHCUT_ANALYZERS=fake RUSHCUT_WORKFLOWS=$PWD/workflows \
  setsid python -m uvicorn backend.app:app --port 8000 </dev/null >/tmp/backend.log 2>&1 &
cd frontend/apps/web
grep -q NEXT_PUBLIC_BACKEND_URL .env.local 2>/dev/null || printf 'NEXT_PUBLIC_BACKEND_URL=http://localhost:8000\n' >> .env.local
setsid ~/.bun/bin/bun run dev </dev/null >/tmp/editor.log 2>&1 &
sleep 10; curl -s localhost:8000/health; curl -s -o /dev/null -w " editor:%{http_code}\n" localhost:3000
```
No dev brain on the box — the backend's defaults hit real Ollama (`qwen3-vl:30b`).

**The loop check (the moment everything has built toward):** open
`http://localhost:3000/rushcut-dev`, type in the AI chat: *"low-angle shot of Dana crossing
the lobby"* → a plan card appears and NOTHING runs → Approve → a job walks the stages and a
real clip comes back (draft tier: ~1–2 min). Paste to chat: **"LOOP GREEN ON REAL WEIGHTS"**
plus how long the clip took. If it errors, paste `/tmp/backend.log` tail.

## Phase 5 — CREATE THE DEMO (the rest of the afternoon)

**5a. Footage (human, 20 min).** Film with the phone: 2–4 short clips of consenting
teammates — one walking through a lobby/hallway, one talking, one wide with a person in the
background. 2–3 clear frontal photos of each. One clip includes the person playing
"unapproved extra" (with their OK — they get flagged on stage; it's the best moment).
Everything into one folder + `CONSENT.txt` (names + "agreed to appear in demo").
**Never push footage to the repo.**

**5b. Cast (10 min).** Ingest the folder (`POST /ingest/footage` or the panel) — fake
analyzers are fine; OR just use the seeded cast (Dana/Marcus/unknown) and name the unknown
after your extra. Cast panel: principals approved, the extra left `unknown`.

**5c. Generate the demo takes (run all afternoon, review as they land).**
For each beat of `docs/DEMO_SCRIPT.md`, generate 3–4 takes via chat and keep the best:
- Beat 2 shot: the "low-angle of <principal>" clip. Vary seed, pick the winner.
- **Beat 3 — consent catch, the real version on this box:** in chat, request a shot that
  references the *unapproved* person → the job is **born policy_blocked before the GPU
  runs** (that's the pre-GPU gate — real, not simulated). Show the blocked clip tint. Then
  approve that person in the Cast panel → regenerate → it runs. That sequence IS beat 3.
- Beat 4: if Tier 3 + hero template exist → edit `scripts/bakery_jobs.json` prompts to match
  your footage and `python3 scripts/bakery.py --run` (leave running). No heroes? The demo
  script's fallback stands: show the best draft take as-is and say draft-tier honestly.

**5d. Stage the bin (15 min).** Best takes organized in the project; every fallback asset
from `docs/DEMO_SCRIPT.md` staged BEFORE rehearsal; the pre-blocked and post-approval clips
saved for beat 3.

## Phase 6 — Lockdown + rehearsal (last 90 min)

1. Warm-run everything once more, **then**: runbook §7 — update checks off, network monitor
   on, confirm silence, then box network dark. Nothing may download on stage.
2. **Rehearse the four beats twice, end to end, on this box, with these assets.** Time it.
   Fix what breaks, not what's ugly.
3. Keep on screen for the close: the Cast panel, one generated file's provenance
   (`ffprobe -show_entries format_tags=comment <file>` — the receipt is in the file), and
   `nemoclaw/egress-policy.yaml`.

## Phase 7 — Submission readiness (human, 10 min, in parallel)

Check the organizer email for the submission form/deadline (rosters/submissions lock —
your teammate's thread says so). Have ready: repo URL
(https://github.com/Wally-Ahmed/dell-hardware-hack), one-line pitch (*"an on-prem video
production agent: new shots from approved people only — nothing leaves the building, and
we can prove both"*), team roster, and the demo order from `docs/DEMO_SCRIPT.md`.
**Also verify from that email:** whether a required planning model (vLLM on :8000) is
mandated — if yes, tell the conductor IMMEDIATELY; it's a two-env-var move for us.

---

## Agent rules recap (unchanged, binding)

Territory: `workflows/` + `scripts/`, branch `box` only. Never ComfyUI-Manager, never
`--gpu-only`, FP8 for diffusion / NVFP4 only for the LLM, nothing that needs an API key,
no footage of real people pushed to the public repo, the box's cloud agent goes OFF at
lockdown. Blocked >10 min → paste-ready error block to team chat, keep moving. Say
"policy-enforced, audited, human-signed-off" — never "guaranteed."
