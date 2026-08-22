#!/usr/bin/env python3
"""RushCut GB10 smoke test — the go/no-go gate for tonight's demo.

Run it with plain system python (stdlib only, no venv needed):

    python3 scripts/smoke_test.py

Three checks:
  A. ComfyUI alive   — GET :8188/system_stats, prints the VRAM/RAM it reports.
  B. Ollama brain    — asks $RUSHCUT_BRAIN (default qwen3-vl:30b) to reply
                       exactly "BOX-OK" via the OpenAI-compatible endpoint.
  C. Generation      — if workflows/wan5b_i2v.json (or the klein template)
                       exists, submits it with a tiny test prompt patched into
                       the RUSHCUT_PROMPT-titled node and polls to completion
                       (up to 15 min). SKIPs if no template exists yet.

Exit code 0 only if A and B PASS and C PASSed or SKIPped.
Whatever happens: PASTE THE WHOLE OUTPUT INTO TEAM CHAT.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

COMFY = os.environ.get("RUSHCUT_COMFY_URL", "http://127.0.0.1:8188")
OLLAMA = os.environ.get("RUSHCUT_OLLAMA_URL", "http://127.0.0.1:11434")
BRAIN = os.environ.get("RUSHCUT_BRAIN", "qwen3-vl:30b")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS_DIR = os.path.join(REPO_ROOT, "workflows")
TEMPLATE_CANDIDATES = ["wan5b_i2v.json", "klein_keyframe_multiref.json"]
TEST_PROMPT = "smoke test: a small wooden desk robot waves at the camera, soft studio light"
TEST_SEED = 8888
GEN_TIMEOUT_S = 15 * 60

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def http_json(url: str, payload=None, timeout: float = 30):
    """POST payload as JSON (or GET when payload is None); return parsed JSON."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def gb(n) -> str:
    try:
        return f"{float(n) / (1024 ** 3):.1f}"
    except (TypeError, ValueError):
        return "?"


def short_err(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = e.read().decode(errors="replace")[:200]
        except Exception:
            body = ""
        return f"HTTP {e.code}: {body}"
    return f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------- check A
def check_comfy():
    try:
        stats = http_json(f"{COMFY}/system_stats", timeout=10)
    except Exception as e:
        return (FAIL, f"no response from {COMFY} ({short_err(e)})",
                "Is ComfyUI up? Run: bash scripts/setup_box.sh <NVME_ROOT>  then: tail -50 <NVME_ROOT>/logs/comfyui.log")
    system = stats.get("system", {}) or {}
    bits = [f"ComfyUI {system.get('comfyui_version', '?')}"]
    if "ram_total" in system:
        bits.append(f"RAM free {gb(system.get('ram_free'))}/{gb(system.get('ram_total'))} GB")
    for dev in stats.get("devices", []) or []:
        bits.append(f"{dev.get('name', 'gpu?')}: VRAM free "
                    f"{gb(dev.get('vram_free'))}/{gb(dev.get('vram_total'))} GB")
    return (PASS, " | ".join(bits), "")


# --------------------------------------------------------------------- check B
def check_ollama():
    payload = {
        "model": BRAIN,
        "messages": [{"role": "user", "content": "Reply with exactly: BOX-OK"}],
        "max_tokens": 10,
        "temperature": 0,
    }
    try:
        # generous timeout: the first call loads the model (~25 s+ for the 30B MoE)
        resp = http_json(f"{OLLAMA}/v1/chat/completions", payload, timeout=300)
    except urllib.error.HTTPError as e:
        detail = short_err(e)
        hint = (f"Model '{BRAIN}' not loaded? Check 'ollama list' — load it per runbook §3 "
                f"(OLLAMA_MODELS must point at the NVMe copy), or set RUSHCUT_BRAIN=qwen3-vl:8b")
        return (FAIL, detail, hint)
    except Exception as e:
        return (FAIL, f"no response from {OLLAMA} ({short_err(e)})",
                "Is Ollama up? Run: bash scripts/setup_box.sh <NVME_ROOT>  then: tail -20 <NVME_ROOT>/logs/ollama.log")
    try:
        content = (resp["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError):
        return (FAIL, f"unexpected response shape: {json.dumps(resp)[:200]}",
                "Ollama answered but not in OpenAI chat format — paste this output to team chat")
    if "BOX-OK" in content:
        return (PASS, f"{BRAIN} replied {content!r}", "")
    return (FAIL, f"{BRAIN} replied {content!r} (wanted 'BOX-OK')",
            "Model is up but off-script — try 'ollama run " + BRAIN + "' by hand and paste to team chat")


# --------------------------------------------------------------------- check C
def patch_rushcut_nodes(workflow: dict) -> list[str]:
    """Patch RUSHCUT_PROMPT / RUSHCUT_SEED titled nodes in an API-format workflow.

    RUSHCUT_IMAGE nodes are left exactly as saved: the template was exported
    from a run that worked in the GUI, so its LoadImage already points at a
    file in ComfyUI/input.
    """
    patched = []
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        title = (node.get("_meta") or {}).get("title", "")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if title == "RUSHCUT_PROMPT":
            key = "text" if isinstance(inputs.get("text"), str) else next(
                (k for k, v in inputs.items() if isinstance(v, str)), None)
            if key:
                inputs[key] = TEST_PROMPT
                patched.append(f"RUSHCUT_PROMPT.{key}")
        elif title == "RUSHCUT_SEED":
            key = next((k for k in ("seed", "noise_seed") if k in inputs), None)
            if key is None:
                key = next((k for k, v in inputs.items()
                            if isinstance(v, int) and not isinstance(v, bool)), None)
            if key:
                inputs[key] = TEST_SEED
                patched.append(f"RUSHCUT_SEED.{key}")
    return patched


def collect_outputs(entry: dict) -> list[str]:
    names = []
    for out in (entry.get("outputs") or {}).values():
        if not isinstance(out, dict):
            continue
        for kind in ("images", "gifs", "videos"):
            for f in out.get(kind, []) or []:
                if isinstance(f, dict) and f.get("filename"):
                    names.append(f["filename"])
    return names


def check_generation():
    template = None
    for cand in TEMPLATE_CANDIDATES:
        p = os.path.join(WORKFLOWS_DIR, cand)
        if os.path.isfile(p):
            template = p
            break
    if template is None:
        return (SKIP, f"no template in {WORKFLOWS_DIR} (looked for {', '.join(TEMPLATE_CANDIDATES)})",
                "build the template first (runbook §5), then re-run this smoke test")

    name = os.path.basename(template)
    try:
        with open(template, encoding="utf-8") as f:
            workflow = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return (FAIL, f"{name} is not readable JSON ({short_err(e)})",
                "re-export it with 'Save (API Format)' — runbook §5 step 5")

    patched = patch_rushcut_nodes(workflow)
    if patched:
        print(f"    patched: {', '.join(patched)}")
    else:
        print("    note: no RUSHCUT_PROMPT/RUSHCUT_SEED titled nodes found — "
              "running the template exactly as saved (titles: runbook §5 step 4)")

    try:
        res = http_json(f"{COMFY}/prompt",
                        {"prompt": workflow, "client_id": "rushcut-smoke"}, timeout=30)
    except urllib.error.HTTPError as e:
        return (FAIL, f"ComfyUI rejected {name}: {short_err(e)}",
                "template references a missing model/node — open it at http://127.0.0.1:8188, queue it once, re-export")
    except Exception as e:
        return (FAIL, f"could not submit to {COMFY} ({short_err(e)})",
                "Is ComfyUI up? (check A must PASS first)")
    prompt_id = res.get("prompt_id")
    if not prompt_id:
        return (FAIL, f"no prompt_id in response: {json.dumps(res)[:200]}",
                "paste this output to team chat")

    print(f"    submitted {name} as {prompt_id}; polling every 5 s (up to 15 min) ", end="", flush=True)
    deadline = time.time() + GEN_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(5)
        print(".", end="", flush=True)
        try:
            hist = http_json(f"{COMFY}/history/{prompt_id}", timeout=10)
        except Exception:
            continue  # transient — keep polling until the deadline
        entry = hist.get(prompt_id)
        if not entry:
            continue
        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            print()
            msgs = json.dumps(status.get("messages", []))[:300]
            return (FAIL, f"{name} errored inside ComfyUI: {msgs}",
                    "tail -50 <NVME_ROOT>/logs/comfyui.log and paste the error to team chat")
        outputs = collect_outputs(entry)
        if outputs or status.get("completed"):
            print()
            shown = ", ".join(outputs) if outputs else "(completed, no file outputs listed)"
            return (PASS, f"{name} -> {shown} (in ComfyUI's output/ dir)", "")
    print()
    return (FAIL, f"{name} still not done after {GEN_TIMEOUT_S // 60} min",
            "check the queue at http://127.0.0.1:8188 — a hero model may be hogging memory; POST /free or restart ComfyUI via setup_box.sh")


# ------------------------------------------------------------------------ main
def run(label: str, fn):
    print(f"== {label} ==")
    t0 = time.time()
    try:
        status, detail, hint = fn()
    except Exception as e:  # a check must never traceback — the teammate pastes, we debug
        status, detail = FAIL, f"unexpected error in the check itself ({short_err(e)})"
        hint = "paste this whole output to team chat"
    dt = time.time() - t0
    print(f"{status} ({dt:.1f}s) — {detail}")
    if hint:
        print(f"    hint: {hint}")
    print()
    return status


def main() -> int:
    print(f"RushCut GB10 smoke test — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"ComfyUI={COMFY}  Ollama={OLLAMA}  brain={BRAIN}")
    print()
    a = run("A. ComfyUI alive", check_comfy)
    b = run(f"B. Ollama brain ({BRAIN})", check_ollama)
    c = run("C. Generation through a saved template", check_generation)

    go = a == PASS and b == PASS and c in (PASS, SKIP)
    print("-" * 60)
    print(f"SMOKE TEST: {'GO' if go else 'NO-GO'}  (A {a}, B {b}, C {c})")
    if not go:
        print("Fix the FAILed check(s) above (each has a hint), then re-run me.")
    print("PASTE THIS WHOLE OUTPUT INTO TEAM CHAT")
    return 0 if go else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted — re-run: python3 scripts/smoke_test.py")
        sys.exit(130)
