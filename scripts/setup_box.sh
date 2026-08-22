#!/usr/bin/env bash
# =============================================================================
# setup_box.sh — RushCut GB10 box setup (Role A — Box & Models)
#
# Usage:   bash scripts/setup_box.sh /path/to/nvme/root
# Example: bash scripts/setup_box.sh "$HOME/rushcut"
#
# IDEMPOTENT: safe to re-run any time (after git pull, after a fix, after
# reboot). Already-running services are detected and left alone.
#
# GB10 gotchas this script bakes in (do not "simplify" these away):
#   * ComfyUI MUST run with --disable-mmap   (unified-memory double-allocation
#     bug: mmap'd safetensors + the "VRAM" copy are the same RAM — halves
#     usable memory to ~64 GB without the flag; budget 2x model size at load)
#   * ComfyUI MUST run with --disable-api-nodes (fully offline, no cloud nodes)
#   * NEVER pass --gpu-only (fights the unified-memory fabric)
#   * NEVER install ComfyUI-Manager (phones home) — this script quarantines it
#   * HF_HUB_DISABLE_TELEMETRY=1 is required ALONGSIDE HF_HUB_OFFLINE=1
#     (HF fires telemetry independently of the offline switch)
#   * onnxruntime has no aarch64 wheel — DWPose/ControlNet preprocessors would
#     silently run on CPU (10x slowdown). Avoid those nodes today.
#   * FP8 for diffusion models, NVFP4 only for the LLM (NVFP4 is weight-only
#     and does not speed up compute-bound video diffusion).
# =============================================================================
set -uo pipefail   # deliberately NOT -e: partial success keeps going; the
                   # summary at the end lists every warning/failure.

# ---------------------------------------------------------------- pretty print
GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; NC=$'\033[0m'
WARNINGS=(); FAILURES=()
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$NC" "$*"; }
warn() { printf '  %s✗%s %s\n' "$YELLOW" "$NC" "$*"; WARNINGS+=("$*"); }
bad()  { printf '  %s✗%s %s\n' "$RED" "$NC" "$*"; FAILURES+=("$*"); }
step() { printf '\n%s== %s ==%s\n' "$BOLD" "$*" "$NC"; }

http_ok() {  # http_ok <url> — exit 0 if the URL answers (curl, else python3)
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -m 3 "$1" >/dev/null 2>&1
  else
    python3 - "$1" <<'PY' >/dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=3)
PY
  fi
}

# ------------------------------------------------------------------- arguments
NVME_ROOT="${1:-${RUSHCUT_NVME_ROOT:-}}"
if [ -z "$NVME_ROOT" ]; then
  echo "Usage: bash scripts/setup_box.sh /path/to/nvme/root"
  echo "  (the folder you rsync'd the USB drive into, e.g. \$HOME/rushcut)"
  echo "  Hint: ls \$HOME/rushcut  /mnt /media to find it."
  exit 2
fi
if [ ! -d "$NVME_ROOT" ]; then
  echo "ERROR: '$NVME_ROOT' is not a directory. Did the rsync in runbook §2 finish?"
  exit 2
fi
NVME_ROOT="$(cd "$NVME_ROOT" && pwd)"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$NVME_ROOT/logs"; RUN_DIR="$NVME_ROOT/run"
mkdir -p "$LOG_DIR" "$RUN_DIR"

echo "${BOLD}RushCut GB10 setup${NC}  NVME_ROOT=$NVME_ROOT  repo=$REPO_ROOT"
echo "(idempotent — re-run me any time; logs land in $LOG_DIR)"

# ----------------------------------------------------------------- 1/8: sanity
step "1/8 Sanity checks"
ARCH="$(uname -m)"
if [ "$ARCH" = "aarch64" ]; then
  ok "arch: aarch64"
else
  warn "arch is '$ARCH', expected aarch64 — is this really the GB10? Continuing, but wheels/models are aarch64-only."
fi

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  ok "GPU: $(nvidia-smi -L 2>/dev/null | head -1)"
else
  bad "nvidia-smi missing or erroring — GPU driver problem. Try a reboot; if it persists, paste 'dmesg | grep -i nvidia' output to team chat."
fi

# Drive layout (warn, don't die — MANIFEST.md on the drive is the ground truth)
for d in hf comfyui_models wheels; do
  if [ -d "$NVME_ROOT/$d" ]; then ok "found $NVME_ROOT/$d"
  else warn "missing $NVME_ROOT/$d — check MANIFEST.md for the real name; paste 'ls $NVME_ROOT' to team chat"
  fi
done
COMFY_DIR=""
for c in "$NVME_ROOT/ComfyUI" "$NVME_ROOT/comfyui" "$NVME_ROOT/ComfyUI-master"; do
  [ -d "$c" ] && COMFY_DIR="$c" && break
done
if [ -n "$COMFY_DIR" ]; then ok "found ComfyUI at $COMFY_DIR"
else warn "no ComfyUI checkout under $NVME_ROOT (looked for ComfyUI/, comfyui/) — ComfyUI steps will be skipped"
fi
CUSTOM_NODES_SRC=""
for c in "$NVME_ROOT/custom_nodes" "$NVME_ROOT/comfyui_custom_nodes" "$NVME_ROOT/nodes"; do
  [ -d "$c" ] && CUSTOM_NODES_SRC="$c" && break
done
if [ -n "$CUSTOM_NODES_SRC" ]; then ok "found custom nodes at $CUSTOM_NODES_SRC"
else warn "no custom_nodes dir under $NVME_ROOT — Wan/VACE/SeedVR2 templates will not load until it exists"
fi

# --------------------------------------------------- 2/8: environment (offline)
step "2/8 Offline / no-telemetry environment (exported now + persisted to ~/.bashrc)"
ENV_LINES=(
  "export HF_HUB_OFFLINE=1"
  "export TRANSFORMERS_OFFLINE=1"
  "export HF_HUB_DISABLE_TELEMETRY=1"   # required ALONGSIDE offline (separate switch)
  "export DO_NOT_TRACK=1"
  "export RUSHCUT_NVME_ROOT=\"$NVME_ROOT\""
  "export RUSHCUT_EXECUTOR=comfy"
  "export PYTORCH_NO_CUDA_MEMORY_CACHING=1"
  "export OLLAMA_NO_ANALYTICS=1"
  "export OLLAMA_NO_UPDATE_CHECK=1"
  "export OLLAMA_HOST=127.0.0.1:11434"
)
for cand in "$NVME_ROOT/ollama" "$NVME_ROOT/ollama_models"; do
  if [ -d "$cand/models" ]; then ENV_LINES+=("export OLLAMA_MODELS=\"$cand/models\""); break
  elif [ -d "$cand" ]; then ENV_LINES+=("export OLLAMA_MODELS=\"$cand\""); break
  fi
done
for line in "${ENV_LINES[@]}"; do eval "$line"; done
BASHRC="$HOME/.bashrc"
MARK_BEGIN="# >>> rushcut box env (managed by scripts/setup_box.sh — edits inside are overwritten) >>>"
MARK_END="# <<< rushcut box env <<<"
touch "$BASHRC"
awk -v b="$MARK_BEGIN" -v e="$MARK_END" '$0==b{skip=1} skip!=1{print} $0==e{skip=0}' \
  "$BASHRC" > "$BASHRC.rushcut.tmp" && mv "$BASHRC.rushcut.tmp" "$BASHRC"
{ echo "$MARK_BEGIN"; printf '%s\n' "${ENV_LINES[@]}"; echo "$MARK_END"; } >> "$BASHRC"
ok "exported ${#ENV_LINES[@]} vars and refreshed the managed block in ~/.bashrc"
ok "NOTE: run 'source ~/.bashrc' in your other terminals to pick these up"

# ------------------------------------------------- 3/8: venv from wheelhouse
step "3/8 Python venv from the offline wheelhouse (no internet used)"
VENV="$NVME_ROOT/venv"; PIP="$VENV/bin/pip"
if [ -x "$VENV/bin/python" ]; then
  ok "venv exists: $VENV"
else
  if python3 -m venv "$VENV" >>"$LOG_DIR/pip.log" 2>&1; then
    ok "created venv: $VENV"
  else
    bad "venv creation failed — try: sudo apt install -y python3.12-venv  (then re-run me)"
  fi
fi
MISSING_PKGS=()
pip_off() {  # pip_off <requirement> — offline install, tolerate missing wheels
  [ -x "$PIP" ] || { MISSING_PKGS+=("$1 (no venv)"); return 1; }
  if "$PIP" install --no-index --find-links "$NVME_ROOT/wheels" "$1" >>"$LOG_DIR/pip.log" 2>&1; then
    ok "pip: $1"
  else
    warn "pip: no wheel satisfied '$1' (details: $LOG_DIR/pip.log)"
    MISSING_PKGS+=("$1")
  fi
}
for p in fastapi uvicorn httpx pydantic pymongo; do pip_off "$p"; done
REQ="$REPO_ROOT/backend/requirements.txt"
if [ -f "$REQ" ]; then
  while IFS= read -r line; do
    line="${line%%#*}"
    line="$(printf '%s' "$line" | tr -d '[:space:]')"
    [ -n "$line" ] && pip_off "$line"
  done < "$REQ"
else
  ok "no backend/requirements.txt on this checkout yet (fine — core deps installed above)"
fi
if [ "${#MISSING_PKGS[@]}" -gt 0 ]; then
  warn "wheels missing for: ${MISSING_PKGS[*]} — tell team chat (Role B may need them added to the drive)"
fi

# -------------------------------------------------------------- 4/8: MongoDB
step "4/8 MongoDB (127.0.0.1 only)"
if command -v mongod >/dev/null 2>&1; then
  if pgrep -x mongod >/dev/null 2>&1; then
    ok "mongod already running"
  else
    mkdir -p "$NVME_ROOT/mongo-data"
    if mongod --dbpath "$NVME_ROOT/mongo-data" --bind_ip 127.0.0.1 --port 27017 \
              --logpath "$LOG_DIR/mongod.log" --fork >/dev/null 2>&1; then
      ok "mongod started on 127.0.0.1:27017 (data: $NVME_ROOT/mongo-data)"
    else
      warn "mongod failed to start — tail -20 $LOG_DIR/mongod.log and paste to team chat (backend can run without it today)"
    fi
  fi
else
  warn "mongod not installed — SKIPPING (backend runs without it today; not demo-blocking)"
fi

# -------------------------------------------------------------- 5/8: ComfyUI
step "5/8 ComfyUI: model symlinks, custom nodes, no-Manager check, start"
if [ -z "$COMFY_DIR" ]; then
  bad "ComfyUI not found under $NVME_ROOT — copy it from the drive, then re-run me"
else
  # -- symlink model dirs: comfyui_models/<type>/* -> ComfyUI/models/<type>/*
  #    expected types: checkpoints diffusion_models loras vae text_encoders
  #                    upscale_models sams insightface (+ extras like rife)
  SRC_MODELS="$NVME_ROOT/comfyui_models"
  if [ -d "$SRC_MODELS" ]; then
    linked=0; skipped=0
    for src in "$SRC_MODELS"/*/; do
      [ -d "$src" ] || continue
      name="$(basename "$src")"
      dst="$COMFY_DIR/models/$name"
      mkdir -p "$dst"
      for item in "$src"*; do
        [ -e "$item" ] || continue
        tgt="$dst/$(basename "$item")"
        if [ -e "$tgt" ] || [ -L "$tgt" ]; then
          skipped=$((skipped+1))
        else
          ln -s "$item" "$tgt" && linked=$((linked+1))
        fi
      done
    done
    ok "model symlinks: $linked new, $skipped already in place"
  else
    warn "no $SRC_MODELS — loader nodes will show empty model lists"
  fi

  # -- custom nodes (expected on the drive: ComfyUI-WanVideoWrapper,
  #    ComfyUI-segment-anything-2, ComfyUI-KJNodes, ComfyUI-VideoHelperSuite,
  #    ComfyUI-SeedVR2_VideoUpscaler, ComfyUI-Frame-Interpolation)
  if [ -n "$CUSTOM_NODES_SRC" ]; then
    mkdir -p "$COMFY_DIR/custom_nodes"
    n_linked=0
    for nd in "$CUSTOM_NODES_SRC"/*/; do
      [ -d "$nd" ] || continue
      name="$(basename "$nd")"
      if [ -e "$COMFY_DIR/custom_nodes/$name" ]; then :; else
        ln -s "${nd%/}" "$COMFY_DIR/custom_nodes/$name" && n_linked=$((n_linked+1))
      fi
    done
    ok "custom nodes: $n_linked newly linked; present now: $(ls -m "$COMFY_DIR/custom_nodes" 2>/dev/null | head -c 300)"
  fi

  # -- assert ComfyUI-Manager is NOT installed (it phones home)
  MGR_HITS="$(find "$COMFY_DIR/custom_nodes" -maxdepth 1 -iname '*comfyui-manager*' 2>/dev/null)"
  if [ -n "$MGR_HITS" ]; then
    warn "ComfyUI-Manager detected — it PHONES HOME and breaks the air-gap:"
    printf '      %s\n' $MGR_HITS
    if [ -t 0 ]; then read -r -p "  Quarantine it now (move to $NVME_ROOT/quarantine)? [Y/n] " ans; else ans="Y"; fi
    case "${ans:-Y}" in
      [Nn]*) bad "ComfyUI-Manager left installed — air-gap verification (runbook §7) WILL fail. Remove before the demo." ;;
      *) mkdir -p "$NVME_ROOT/quarantine"
         for m in $MGR_HITS; do mv "$m" "$NVME_ROOT/quarantine/" 2>/dev/null; done
         ok "moved to $NVME_ROOT/quarantine/ (restart of ComfyUI below picks this up)" ;;
    esac
  else
    ok "ComfyUI-Manager not installed (correct — never install it)"
  fi

  # -- start ComfyUI with the GB10-mandatory flags
  if http_ok "http://127.0.0.1:8188/system_stats"; then
    ok "ComfyUI already up at http://127.0.0.1:8188 (leaving it alone)"
    ok "  (started it by hand without --disable-mmap? kill it: kill \$(cat $RUN_DIR/comfyui.pid) or pkill -f 'main.py --listen', then re-run me)"
  else
    COMFY_PY=""
    if [ -x "$COMFY_DIR/venv/bin/python" ]; then
      COMFY_PY="$COMFY_DIR/venv/bin/python"
    elif [ -x "$VENV/bin/python" ]; then
      COMFY_PY="$VENV/bin/python"
      # best-effort: ComfyUI deps from the wheelhouse (tolerant, logged)
      if [ -f "$COMFY_DIR/requirements.txt" ]; then
        while IFS= read -r line; do
          line="${line%%#*}"; line="$(printf '%s' "$line" | tr -d '[:space:]')"
          [ -n "$line" ] && pip_off "$line"
        done < "$COMFY_DIR/requirements.txt"
      fi
    else
      COMFY_PY="python3"
    fi
    # Flags, per the GB10 gotchas: --disable-mmap (double-allocation bug),
    # --disable-api-nodes (offline). NO --gpu-only — EVER (unified memory).
    (
      cd "$COMFY_DIR" && \
      nohup "$COMFY_PY" main.py \
        --listen 127.0.0.1 --port 8188 \
        --disable-mmap --disable-api-nodes \
        >>"$LOG_DIR/comfyui.log" 2>&1 &
      echo $! > "$RUN_DIR/comfyui.pid"
    )
    printf '  waiting for ComfyUI (up to 120s) '
    waited=0; comfy_up=0
    while [ "$waited" -lt 120 ]; do
      if http_ok "http://127.0.0.1:8188/system_stats"; then comfy_up=1; break; fi
      printf '.'; sleep 3; waited=$((waited+3))
    done
    echo ""
    if [ "$comfy_up" = "1" ]; then
      ok "ComfyUI up at http://127.0.0.1:8188 (pid $(cat "$RUN_DIR/comfyui.pid" 2>/dev/null), log $LOG_DIR/comfyui.log)"
    else
      bad "ComfyUI did not answer within 120s — run: tail -50 $LOG_DIR/comfyui.log  and paste to team chat"
    fi
  fi
fi

# --------------------------------------------------------------- 6/8: Ollama
step "6/8 Ollama (agent brain: qwen3-vl:30b)"
if command -v ollama >/dev/null 2>&1; then
  if http_ok "http://127.0.0.1:11434"; then
    ok "ollama already serving on 127.0.0.1:11434"
  else
    nohup ollama serve >>"$LOG_DIR/ollama.log" 2>&1 &
    echo $! > "$RUN_DIR/ollama.pid"
    printf '  waiting for ollama (up to 30s) '
    waited=0; ollama_up=0
    while [ "$waited" -lt 30 ]; do
      if http_ok "http://127.0.0.1:11434"; then ollama_up=1; break; fi
      printf '.'; sleep 2; waited=$((waited+2))
    done
    echo ""
    if [ "$ollama_up" = "1" ]; then ok "ollama serving on 127.0.0.1:11434 (log $LOG_DIR/ollama.log)"
    else bad "ollama serve did not come up — tail -20 $LOG_DIR/ollama.log and paste to team chat"
    fi
  fi
  echo "  models ollama can see:"
  ollama list 2>/dev/null | sed 's/^/    /' || true
  if ollama list 2>/dev/null | grep -q "qwen3-vl:30b"; then
    ok "qwen3-vl:30b present"
  else
    warn "qwen3-vl:30b NOT in 'ollama list'. Load it from the NVMe copy:"
    echo "      - if the drive shipped an ollama model store, this script already exported OLLAMA_MODELS when \$NVME_ROOT/ollama exists — run 'source ~/.bashrc', restart ollama (kill \$(cat $RUN_DIR/ollama.pid)), re-run me"
    echo "      - else check MANIFEST.md on the drive; typical form: ollama create qwen3-vl:30b -f \"$NVME_ROOT/ollama/Modelfile\""
    echo "      - fallback brain (smaller): qwen3-vl:8b — then run smoke test with RUSHCUT_BRAIN=qwen3-vl:8b"
  fi
else
  bad "ollama not installed — find the aarch64 ollama tarball on the drive (MANIFEST.md) and install it; the agent brain needs it"
fi

# -------------------------------------------------------------- 7/8: backend
step "7/8 FastAPI backend"
if [ -f "$REPO_ROOT/backend/app.py" ]; then
  if http_ok "http://127.0.0.1:8000/docs" || http_ok "http://127.0.0.1:8000/openapi.json"; then
    ok "backend already up at http://127.0.0.1:8000"
  elif [ -x "$VENV/bin/uvicorn" ]; then
    (
      cd "$REPO_ROOT" && \
      nohup "$VENV/bin/uvicorn" backend.app:app --host 127.0.0.1 --port 8000 \
        >>"$LOG_DIR/backend.log" 2>&1 &
      echo $! > "$RUN_DIR/backend.pid"
    )
    sleep 3
    if http_ok "http://127.0.0.1:8000/docs" || http_ok "http://127.0.0.1:8000/openapi.json"; then
      ok "backend up at http://127.0.0.1:8000 (log $LOG_DIR/backend.log)"
    else
      warn "backend not answering yet — tail -30 $LOG_DIR/backend.log and paste to team chat"
    fi
  else
    warn "uvicorn missing from the venv (wheel gap above) — backend not started"
  fi
else
  warn "backend/app.py not on this checkout yet — it lands via git pull. Later: 'git pull' then re-run me (safe to re-run)."
fi

# --------------------------------------------------------------- 8/8: summary
step "8/8 SUMMARY"
svc() {  # svc <name> <url>
  if http_ok "$2"; then printf '  %s✓ up%s   %-8s %s\n' "$GREEN" "$NC" "$1" "$2"
  else printf '  %s✗ down%s %-8s %s\n' "$RED" "$NC" "$1" "$2"
  fi
}
svc "ComfyUI" "http://127.0.0.1:8188/system_stats"
svc "Ollama"  "http://127.0.0.1:11434"
svc "Backend" "http://127.0.0.1:8000/openapi.json"
if pgrep -x mongod >/dev/null 2>&1; then printf '  %s✓ up%s   MongoDB  127.0.0.1:27017\n' "$GREEN" "$NC"
else printf '  %s✗ down%s MongoDB  (optional today)\n' "$YELLOW" "$NC"; fi
echo "  logs: $LOG_DIR    pidfiles: $RUN_DIR"

if [ "${#WARNINGS[@]}" -gt 0 ]; then
  printf '\n%sWarnings (%d) — continue, but tell team chat:%s\n' "$YELLOW" "${#WARNINGS[@]}" "$NC"
  printf '  - %s\n' "${WARNINGS[@]}"
fi
if [ "${#FAILURES[@]}" -gt 0 ]; then
  printf '\n%sFailures (%d) — fix these (each line says how), then re-run me:%s\n' "$RED" "${#FAILURES[@]}" "$NC"
  printf '  - %s\n' "${FAILURES[@]}"
fi

printf '\n%sNEXT:%s  source ~/.bashrc\n' "$BOLD" "$NC"
printf '       python3 %s/scripts/smoke_test.py   %s<- paste its output into team chat (go/no-go gate)%s\n' "$REPO_ROOT" "$BOLD" "$NC"

if [ "${#FAILURES[@]}" -eq 0 ]; then exit 0; else exit 1; fi
