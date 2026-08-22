#!/usr/bin/env python3
"""RushCut hero bakery — background queue for hero-quality demo clips.

WHY THIS EXISTS: hero models (Wan 2.2 14B fp8 + Lightning 4-step LoRAs) take
3-6 minutes per 720p 5 s clip on the GB10 — this box is 2.75-4.7x slower than
a desktop 5090, and 15+ min per clip without the Lightning LoRAs. So hero
takes are NEVER generated live: this queue bakes them in the background all
afternoon (start by ~14:30, non-negotiable) while the live demo generates with
the fast draft tier. The pitch then shows both: draft live, hero pre-baked.

Usage (stdlib only — plain python3, no venv needed):

    python3 scripts/bakery.py --list      # show the queue + estimated minutes
    python3 scripts/bakery.py --run       # bake everything, sequentially

Behavior:
  * Jobs come from scripts/bakery_jobs.json (edit prompts/seeds to the real
    demo shots with team chat before running).
  * Each job loads workflows/<template>.json (API format) and patches the
    RUSHCUT_PROMPT / RUSHCUT_SEED titled nodes — the same convention the
    backend uses. RUSHCUT_IMAGE nodes stay as saved in the template.
  * Outputs are downloaded into $RUSHCUT_NVME_ROOT/bakery_output/<job_id>/
    plus a provenance manifest.json (model, template, prompt, seed, timing).
  * RESUMABLE: jobs whose output folder already has files are skipped, so
    re-running after a crash or Ctrl-C continues where it left off.
  * Ctrl-C safe: interrupts the current ComfyUI job, keeps finished outputs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
COMFY = os.environ.get("RUSHCUT_COMFY_URL", "http://127.0.0.1:8188")
JOBS_FILE = os.path.join(SCRIPT_DIR, "bakery_jobs.json")
WORKFLOWS_DIR = os.path.join(REPO_ROOT, "workflows")
OUT_ROOT = os.path.join(os.environ.get("RUSHCUT_NVME_ROOT", REPO_ROOT), "bakery_output")
MANIFEST = os.path.join(OUT_ROOT, "manifest.json")
DEFAULT_EST_MIN = 6      # rough per-clip default on this box (Lightning LoRAs)
POLL_S = 10
JOB_TIMEOUT_S = 120 * 60  # seedvr2 upscales legitimately run 50-90 min

# provenance: template -> model id (from backend/models/registry.json)
TEMPLATE_MODEL = {
    "klein_keyframe_multiref": "flux2-klein-4b",
    "wan5b_i2v": "wan2.2-ti2v-5b",
    "wan14b_i2v_lightning": "wan2.2-i2v-14b + wan2.2-lightning-lora",
    "vace_inpaint_person": "wan2.1-vace-1.3b",
    "fun_inpaint_person": "wan2.2-fun-inpaint-14b",
    "fun_camera_reangle": "wan2.2-fun-camera-14b",
    "animate_replace": "wan2.2-animate-14b",
    "seedvr2_upscale": "seedvr2-3b",
    "flux2dev_keyframe": "flux2-dev",
    "qwen_image_edit": "qwen-image-edit-2511",
    "span_upscale": "span",
    "rife_interp": "rife-4.9",
}


def http_json(url: str, payload=None, timeout: float = 30):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
        return json.loads(body) if body else {}


def load_jobs() -> list[dict]:
    if not os.path.isfile(JOBS_FILE):
        print(f"ERROR: {JOBS_FILE} missing — it ships with the repo; git pull, or ask team chat.")
        sys.exit(2)
    with open(JOBS_FILE, encoding="utf-8") as f:
        return json.load(f)["jobs"]


def job_done(job: dict) -> bool:
    d = os.path.join(OUT_ROOT, job["id"])
    return os.path.isdir(d) and any(os.scandir(d))


def template_path(job: dict) -> str:
    return os.path.join(WORKFLOWS_DIR, job["template"] + ".json")


def patch_rushcut_nodes(workflow: dict, prompt: str, seed: int) -> list[str]:
    """Same RUSHCUT_* title convention the backend patches (see runbook §5)."""
    patched = []
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        title = (node.get("_meta") or {}).get("title", "")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if title == "RUSHCUT_PROMPT" and prompt:
            key = "text" if isinstance(inputs.get("text"), str) else next(
                (k for k, v in inputs.items() if isinstance(v, str)), None)
            if key:
                inputs[key] = prompt
                patched.append(f"RUSHCUT_PROMPT.{key}")
        elif title == "RUSHCUT_SEED":
            key = next((k for k in ("seed", "noise_seed") if k in inputs), None)
            if key is None:
                key = next((k for k, v in inputs.items()
                            if isinstance(v, int) and not isinstance(v, bool)), None)
            if key:
                inputs[key] = seed
                patched.append(f"RUSHCUT_SEED.{key}")
    return patched


def collect_outputs(entry: dict) -> list[dict]:
    files = []
    for out in (entry.get("outputs") or {}).values():
        if not isinstance(out, dict):
            continue
        for kind in ("images", "gifs", "videos"):
            for f in out.get(kind, []) or []:
                if isinstance(f, dict) and f.get("filename"):
                    files.append({"filename": f["filename"],
                                  "subfolder": f.get("subfolder", ""),
                                  "type": f.get("type", "output")})
    return files


def download_output(f: dict, dest_dir: str) -> str:
    q = urllib.parse.urlencode(
        {"filename": f["filename"], "subfolder": f["subfolder"], "type": f["type"]})
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f["filename"])
    with urllib.request.urlopen(f"{COMFY}/view?{q}", timeout=120) as r, open(dest, "wb") as w:
        while chunk := r.read(1 << 20):
            w.write(chunk)
    return dest


def append_manifest(entry: dict) -> None:
    os.makedirs(OUT_ROOT, exist_ok=True)
    manifest = []
    if os.path.isfile(MANIFEST):
        try:
            with open(MANIFEST, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            manifest = []
    manifest.append(entry)
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    os.replace(tmp, MANIFEST)


# ---------------------------------------------------------------------- --list
def cmd_list(jobs: list[dict]) -> int:
    print(f"Hero bakery queue ({JOBS_FILE})")
    print(f"outputs -> {OUT_ROOT}\n")
    print(f"{'#':<3}{'id':<30}{'template':<24}{'est':>5}  status")
    pending_min = 0
    pending = 0
    for i, job in enumerate(jobs, 1):
        est = int(job.get("est_minutes", DEFAULT_EST_MIN))
        if job_done(job):
            status = "done (will skip)"
        elif not os.path.isfile(template_path(job)):
            status = f"BLOCKED: workflows/{job['template']}.json missing (runbook §5)"
        else:
            status = "pending"
            pending += 1
            pending_min += est
        print(f"{i:<3}{job['id']:<30}{job['template']:<24}{est:>4}m  {status}")
        if job.get("references"):
            print(f"{'':<3}  refs: {job['references']}")
    print(f"\npending: {pending} job(s), ~{pending_min} min sequential"
          f" (estimates use {DEFAULT_EST_MIN} min/clip default)")
    print("start baking:  python3 scripts/bakery.py --run    (by ~14:30!)")
    return 0


# ----------------------------------------------------------------------- --run
def run_job(job: dict) -> dict | None:
    """Submit one job, poll to completion, download outputs. None on failure."""
    tpath = template_path(job)
    with open(tpath, encoding="utf-8") as f:
        workflow = json.load(f)
    seed = int(job.get("seed", 0))
    patched = patch_rushcut_nodes(workflow, job.get("prompt", ""), seed)
    print(f"  patched: {', '.join(patched) if patched else '(nothing — template runs as saved)'}")

    started = time.time()
    res = http_json(f"{COMFY}/prompt", {"prompt": workflow, "client_id": "rushcut-bakery"})
    prompt_id = res.get("prompt_id")
    if not prompt_id:
        print(f"  FAILED to queue: {json.dumps(res)[:200]}")
        return None
    print(f"  queued as {prompt_id}; polling every {POLL_S}s ", end="", flush=True)

    deadline = started + JOB_TIMEOUT_S
    entry = None
    while time.time() < deadline:
        time.sleep(POLL_S)
        elapsed = int(time.time() - started)
        if elapsed % 60 < POLL_S:
            print(f"[{elapsed // 60}m]", end="", flush=True)
        else:
            print(".", end="", flush=True)
        try:
            hist = http_json(f"{COMFY}/history/{prompt_id}", timeout=10)
        except Exception:
            continue  # transient; keep polling
        e = hist.get(prompt_id)
        if not e:
            continue
        status = e.get("status") or {}
        if status.get("status_str") == "error":
            print(f"\n  FAILED inside ComfyUI: {json.dumps(status.get('messages', []))[:300]}")
            print("  hint: tail -50 $RUSHCUT_NVME_ROOT/logs/comfyui.log and paste to team chat")
            return None
        if collect_outputs(e) or status.get("completed"):
            entry = e
            break
    print()
    if entry is None:
        print(f"  FAILED: not done after {JOB_TIMEOUT_S // 60} min — check http://127.0.0.1:8188")
        return None

    files = collect_outputs(entry)
    dest_dir = os.path.join(OUT_ROOT, job["id"])
    saved = []
    for f in files:
        try:
            saved.append(download_output(f, dest_dir))
        except Exception as e:
            print(f"  warn: could not download {f['filename']} ({e}) — it is still in ComfyUI/output/")
    if not saved:
        # completed but nothing downloadable: leave a marker so resume skips it
        os.makedirs(dest_dir, exist_ok=True)
        marker = os.path.join(dest_dir, "COMPLETED_no_files.txt")
        with open(marker, "w", encoding="utf-8") as f:
            f.write(f"prompt_id {prompt_id} completed but listed no file outputs\n")
        saved.append(marker)
    dur = int(time.time() - started)
    print(f"  done in {dur // 60}m{dur % 60:02d}s -> {', '.join(os.path.basename(s) for s in saved)}")

    return {  # provenance — every generated asset carries it
        "job_id": job["id"],
        "template": job["template"],
        "model": TEMPLATE_MODEL.get(job["template"], "unknown"),
        "prompt": job.get("prompt", ""),
        "seed": seed,
        "references": job.get("references", ""),
        "prompt_id": prompt_id,
        "outputs": saved,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
        "duration_s": dur,
        "status": "ok",
    }


def cmd_run(jobs: list[dict]) -> int:
    print(f"Hero bakery starting — {len(jobs)} job(s), outputs -> {OUT_ROOT}")
    print("(Ctrl-C is safe: finished jobs are kept and --run resumes where it left off)\n")
    try:
        http_json(f"{COMFY}/system_stats", timeout=5)
    except Exception as e:
        print(f"ERROR: ComfyUI not answering at {COMFY} ({type(e).__name__}) —")
        print("       run: bash scripts/setup_box.sh <NVME_ROOT>   then retry")
        return 1

    baked = skipped = missing = failed = 0
    current_id = None
    try:
        for i, job in enumerate(jobs, 1):
            print(f"[{i}/{len(jobs)}] {job['id']} ({job['template']})")
            if job_done(job):
                print("  already baked — skipping (delete "
                      f"{os.path.join(OUT_ROOT, job['id'])} to redo)\n")
                skipped += 1
                continue
            if not os.path.isfile(template_path(job)):
                print(f"  SKIP: workflows/{job['template']}.json does not exist yet (runbook §5)\n")
                missing += 1
                continue
            current_id = job["id"]
            result = run_job(job)
            current_id = None
            if result:
                append_manifest(result)
                baked += 1
            else:
                failed += 1
            print()
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        try:  # best-effort: stop the in-flight ComfyUI job too
            http_json(f"{COMFY}/interrupt", {}, timeout=5)
            if current_id:
                print(f"  sent /interrupt to ComfyUI (job '{current_id}' will re-bake on resume)")
        except Exception:
            pass
        print("Finished jobs are saved. Resume with: python3 scripts/bakery.py --run")
        return 130

    print("-" * 60)
    print(f"BAKERY DONE: {baked} baked, {skipped} already done, "
          f"{missing} blocked on missing templates, {failed} failed")
    print(f"outputs + provenance manifest: {OUT_ROOT}")
    if missing:
        print("missing templates: build them in the ComfyUI GUI (runbook §5), then re-run --run")
    if failed:
        print("failures: paste the FAILED lines above into team chat")
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="RushCut hero bakery queue (see module docstring)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="show the queue and estimates")
    g.add_argument("--run", action="store_true", help="bake all pending jobs sequentially")
    args = ap.parse_args()
    jobs = load_jobs()
    return cmd_list(jobs) if args.list else cmd_run(jobs)


if __name__ == "__main__":
    sys.exit(main())
