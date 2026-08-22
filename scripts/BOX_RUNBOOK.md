# GB10 Box Runbook — Role A (Box & Models)

You are standing at the Dell Pro Max GB10 (NVIDIA GB10, aarch64 Ubuntu 24.04, 128 GB
unified memory). You need zero project context to do this. Follow the numbered steps,
copy-paste the commands, and **paste the outputs into team chat** whenever a step says so.

---

## 0. What you are doing and why it matters

- Everything the team builds today runs on this box; nothing works until the box works.
- Your job: copy the USB drive to internal storage, run one setup script, run one smoke test, save four workflow files, start a batch queue.
- The smoke test output is the team's **go/no-go gate** for tonight's demo — paste it to chat.
- The **hero bakery must start by ~14:30**: this hardware is 2.75–4.7x slower than a desktop 5090, and the demo's best clips bake in the background all afternoon.
- When anything errors, paste the exact text into team chat — Claude debugs through you.

---

## 1. Physical setup

1. **Plug a monitor into the box, or a 4K HDMI dummy plug.** This is REQUIRED, not
   cosmetic: the GB10's GPU only produces a display framebuffer when it detects a display.
   No display = no desktop, no browser on the box, weird GPU behavior.
2. Plug the box straight into a wall outlet (no flaky power strip). It has **no battery** —
   a power blip mid-demo kills the demo.
3. Plug in the **USB flash drive** (it has all models and software; read `MANIFEST.md` on it).
4. Log in, open a terminal. Disable screen blanking so nothing sleeps mid-generation:

   ```bash
   gsettings set org.gnome.desktop.session idle-delay 0
   gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
   ```

---

## 2. Copy drive → NVMe (start this FIRST, it takes a while)

**Never run models off the USB drive.** USB bandwidth starves the models and the drive can
drop mid-read. Everything gets copied to the internal NVMe once, up front.

1. Find where the drive mounted:

   ```bash
   lsblk -o NAME,SIZE,MOUNTPOINT | grep -v loop
   ls /media/$USER/
   ```

   Expect something like `/media/<you>/RUSHCUT` (name may differ — use whatever `ls` shows).

2. Pick the NVMe destination and copy (trailing slashes matter — keep them exactly):

   ```bash
   export NVME_ROOT="$HOME/rushcut"        # any internal path with ~1 TB free is fine
   mkdir -p "$NVME_ROOT"
   rsync -ah --info=progress2 --partial "/media/$USER/RUSHCUT/" "$NVME_ROOT/"
   ```

   `--info=progress2` shows one overall progress line. **Expected duration: 20–45+ minutes**
   for a few hundred GB at USB speeds. Do NOT wait idle — go do §8 (side quests) now.

3. When it finishes, verify the layout:

   ```bash
   ls "$NVME_ROOT"
   ```

   Expected (names close to): `hf/  comfyui_models/  wheels/  ComfyUI/  custom_nodes/  ollama/  MANIFEST.md`

   - **If a folder is missing:** check `MANIFEST.md` on the drive for the real names, and
     paste `ls "$NVME_ROOT"` output into team chat.
   - **If rsync stalls or errors:** re-run the same rsync command — `--partial` resumes.

4. Get the team repo onto the box (ask team chat for the URL):

   ```bash
   cd ~ && git clone <REPO-URL-FROM-TEAM-CHAT> dell-hardware-hack
   cd ~/dell-hardware-hack
   ```

   Already cloned? Just `cd ~/dell-hardware-hack && git pull`.

---

## 3. Run the setup script

From the repo root:

```bash
cd ~/dell-hardware-hack
bash scripts/setup_box.sh "$NVME_ROOT"
source ~/.bashrc        # picks up the environment the script just persisted
```

The script is **idempotent — safe to re-run any time** (after a `git pull`, after a fix,
after a reboot). It does, with a `✓`/`✗` per step:

- sanity checks (aarch64, GPU driver, drive layout)
- exports + persists the offline/no-telemetry environment (`HF_HUB_OFFLINE`, etc.)
- builds a Python venv from the offline wheelhouse (no internet needed)
- starts MongoDB (if installed), ComfyUI (with the GB10-mandatory flags), Ollama, and the
  backend (if it has landed in the repo yet)
- quarantines ComfyUI-Manager if it somehow got installed (it phones home)

**What success looks like:** a final `SUMMARY` block where ComfyUI and Ollama show `✓ up`,
with URLs and log paths. Warnings (`✗` in yellow) are OK to continue past — the summary
lists them; paste the whole summary into team chat either way.

**If ComfyUI shows ✗:** run `tail -50 "$NVME_ROOT/logs/comfyui.log"` and paste it to chat.

---

## 4. Smoke test — the go/no-go gate

```bash
python3 scripts/smoke_test.py
```

Three checks, in order:

| Check | What it does | Roughly |
|---|---|---|
| A. ComfyUI alive | Hits the ComfyUI API, prints VRAM/RAM it sees | instant |
| B. Ollama brain | Asks qwen3-vl:30b to reply exactly `BOX-OK` | 5 s – 2 min (first call loads the model) |
| C. Generation | Runs one real clip/image through a saved workflow template | 1–15 min, prints progress dots |

Check C **SKIPs** (not fails) until you've built the first template in §5 — that's fine on
the first pass. Run the smoke test again after §5 to get a full A+B+C pass.

Expected shape of a good run:

```
== A. ComfyUI alive ==            PASS (0.1s) — RAM free ... | VRAM free ...
== B. Ollama brain (qwen3-vl:30b) ==  PASS (8.2s) — replied 'BOX-OK'
== C. Generation (wan5b_i2v) ==   PASS (170s) — output: wan5b_00001.mp4
SMOKE TEST: GO
PASTE THIS WHOLE OUTPUT INTO TEAM CHAT
```

**PASTE THE WHOLE OUTPUT INTO TEAM CHAT — pass or fail.** This output is the team's
go/no-go gate. Every FAIL line includes a one-line hint; do the hint, re-run, paste again.

---

## 5. Workflow templates (the four priority ones)

The backend never contains inference code — it drives ComfyUI by loading saved workflow
JSON files from the repo's `workflows/` folder and patching values into them. **You** create
those files by clicking a workflow together in the ComfyUI GUI and exporting it.

The naming convention that makes patching work: give the input nodes these exact **titles**
(all caps, exact spelling):

- `RUSHCUT_PROMPT` — on the positive-prompt text node (backend patches the prompt here)
- `RUSHCUT_SEED` — on the sampler/seed node (backend patches the seed here)
- `RUSHCUT_IMAGE` — on the Load Image node, where the workflow takes an input image

Build these four, in this order (models are already on NVMe; loaders will list them):

| # | Save as `workflows/<name>.json` | What it is | Model files it uses |
|---|---|---|---|
| 1 | `klein_keyframe_multiref` | fast keyframe / multi-reference image | `checkpoints/flux2_klein_4b.safetensors` |
| 2 | `wan5b_i2v` | 720p image→video, the live-demo model | `diffusion_models/wan2.2_ti2v_5B_fp16.safetensors` + `vae/wan2.2_vae` + `text_encoders/umt5_xxl_fp8_e4m3fn_scaled` |
| 3 | `vace_inpaint_person` | remove/replace a person (masked video edit) | `diffusion_models/wan2.1_vace_1.3B_fp16.safetensors` + `vae/wan_2.1_vae` |
| 4 | `seedvr2_upscale` | hero video upscale | `upscale_models/seedvr2_3b_fp8.safetensors` (SeedVR2 custom node) |

### Step-by-step: saving one template (do this for each)

1. Open a browser **on the box**: `http://localhost:8188` (this is why the display/dummy
   plug matters).
2. Build the workflow (team chat can send you a reference screenshot/JSON for each). The
   custom nodes for Wan/VACE/SeedVR2 are already installed by the setup script
   (WanVideoWrapper, KJNodes, VideoHelperSuite, SeedVR2, SAM2, Frame-Interpolation).
3. Click **Queue Prompt** once and confirm it actually produces an output. A template that
   never ran is a template that doesn't work.
4. Title the input nodes: **right-click the node → Title** (older UI: Properties → Title)
   → type `RUSHCUT_PROMPT` / `RUSHCUT_SEED` / `RUSHCUT_IMAGE` on the matching nodes.
5. Export in **API format** (a plain JSON of nodes — NOT the normal Save):
   - Newer UI: menu **Workflow → Export (API)**.
   - Older UI: gear icon → enable **Dev mode Options** → a **Save (API Format)** button
     appears in the menu.
6. Save/move the file to the repo with the exact name, e.g.:

   ```bash
   mkdir -p ~/dell-hardware-hack/workflows
   mv ~/Downloads/workflow_api.json ~/dell-hardware-hack/workflows/wan5b_i2v.json
   ```

7. Tell team chat the template name is saved (they pull it into git if you're not pushing).
8. After template #2 (`wan5b_i2v`) exists, re-run `python3 scripts/smoke_test.py` —
   check C now runs a real generation. Paste the output to chat.

**If a loader node shows an empty model list:** the symlinks may predate a ComfyUI start —
re-run `bash scripts/setup_box.sh "$NVME_ROOT"`, then refresh the browser (Ctrl-R).

---

## 6. Start the hero bakery (deadline: ~14:30)

Hero-quality clips take 3–6 minutes each on this box — they bake in the background all
afternoon while the live demo uses fast draft models. The queue lives in
`scripts/bakery_jobs.json` (edit the prompts/seeds with team chat to match the real demo
shots first).

```bash
cd ~/dell-hardware-hack
python3 scripts/bakery.py --list     # shows the queue + estimated minutes
```

Start it (in `nohup` so closing the terminal doesn't kill it):

```bash
nohup python3 scripts/bakery.py --run >> "$NVME_ROOT/logs/bakery.log" 2>&1 &
tail -f "$NVME_ROOT/logs/bakery.log"     # Ctrl-C stops the tail, NOT the bakery
```

- Outputs + a provenance manifest land in `$NVME_ROOT/bakery_output/`.
- It is **resumable**: if it dies or you Ctrl-C a foreground run, re-running `--run`
  skips everything already finished.
- **Start it by 14:30 even if only two jobs are ready.** Late start = no hero clips at demo.

---

## 7. Air-gap verification (before the demo)

Judges may watch the network. The setup script already set the offline environment
(`HF_HUB_OFFLINE`, `HF_HUB_DISABLE_TELEMETRY`, Ollama analytics/update-check off), started
ComfyUI with `--disable-api-nodes`, and quarantined ComfyUI-Manager. Now prove it:

1. Do a final `git pull` (last time the box needs internet), then re-run
   `bash scripts/setup_box.sh "$NVME_ROOT"` if anything changed.
2. Run the network monitor for 60 seconds while generating something:

   ```bash
   sudo timeout 60 tcpdump -n -i any 'not net 127.0.0.0/8 and not arp and not port 5353 and not net 169.254.0.0/16'
   ```

   **Expected: `0 packets captured`** (headers aside). No sudo? Use this instead —
   expect empty output:

   ```bash
   for i in 1 2 3 4 5 6; do ss -tupn state established | grep -v 127.0.0.1; sleep 10; done
   ```

3. If any line appears: note the destination IP/port, paste it into team chat, and we hunt
   it down. (Traffic to the laptop over the USB-C link is expected if the editor UI runs
   there — internet-bound traffic is what must be silent.)
4. The zero-doubt finisher once the last `git pull` is done: **turn Wi-Fi off / unplug
   Ethernet.** Everything runs locally; the box needs no network for the demo.

---

## 8. While things install — side quests

Do these during the rsync (§2) and while models load:

1. **Collect demo footage of CONSENTING teammates** — consent is literally the product
   (the demo's punchline is "only approved people appear"). Ask out loud; only people who
   say yes. Per person: 2–3 clips of 10–20 s (lobby walk, at a desk, two people talking)
   plus 5–10 stills, decent light, phone held landscape. Transfer to the box (USB or cable)
   into:

   ```bash
   mkdir -p "$NVME_ROOT/demo_footage/<FirstName>"
   ```

2. **Set up the projector/display for the pitch** — plug it in early, pick the resolution,
   decide mirror vs extend. Discovering a dead HDMI port at 17:45 is not a plan.
3. **Keep the box on wall power the whole day** (no battery; see §1).

---

## If something breaks

Symptom → cause → fix. All six of these are GB10-specific and each one costs an hour if
you rediscover it from scratch. The setup script already bakes in every fix marked
*(script does this)* — the table exists for when someone bypasses the script.

| Symptom | Cause | Fix |
|---|---|---|
| Out-of-memory at ~64 GB when the box has 128 GB; models that should fit, don't | ComfyUI unified-memory double-allocation: safetensors get mmap'd into RAM, then copied into "VRAM" — which is the same RAM | Run ComfyUI with `--disable-mmap` *(script does this)*. Budget 2x model size during load. If someone started ComfyUI by hand: `kill $(cat "$NVME_ROOT/run/comfyui.pid")` (or `pkill -f 'main.py --listen'`) and re-run the setup script |
| ComfyUI makes network calls / "API nodes" appear | Cloud API nodes enabled by default | Start with `--disable-api-nodes` *(script does this)* |
| DWPose / ControlNet preprocessing is mysteriously ~10x slow | ONNX Runtime has no aarch64 wheel on PyPI, so those nodes silently fall back to CPU | Avoid DWPose/ControlNet-preprocessor nodes today — none of the four priority templates need them |
| Generation slow or OOM after adding `--gpu-only` | `--gpu-only` fights the unified-memory fabric | Never pass it. Kill ComfyUI and re-run the setup script (which starts it with the right flags) |
| Anything phones home from ComfyUI | ComfyUI-Manager is installed | Never install it. If present, the setup script prompts and moves it to `$NVME_ROOT/quarantine/` |
| HF telemetry fires even with `HF_HUB_OFFLINE=1` | Telemetry is a separate switch | `HF_HUB_DISABLE_TELEMETRY=1` must also be set *(script sets both — run `source ~/.bashrc`)* |
| Black screen / no desktop / can't open a browser on the box | GPU produces no framebuffer without a detected display | Plug in the monitor or the 4K HDMI dummy plug (§1), reboot if it was booted headless |
| Tempted to use NVFP4 to speed up video generation | NVFP4 is weight-only; video diffusion here is compute-bound — it does not help | FP8 for diffusion models, NVFP4 only for the LLM. Don't spend time re-quantizing |

Logs live in `$NVME_ROOT/logs/` (`comfyui.log`, `ollama.log`, `backend.log`, `mongod.log`,
`bakery.log`, `pip.log`); PID files in `$NVME_ROOT/run/`.

**For anything not in the table: paste the exact error text (plus the last ~30 lines of the
relevant log) into team chat — Claude debugs through you.**
