# Model Downloads — demo priority order

**Do this BEFORE `setup_box.sh`** (it persists `HF_HUB_OFFLINE=1`; downloads die after
that unless you `unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE` in the shell).
Stop at whatever tier the pipe/clock allows — Tier 1 alone is a complete live demo.
If anyone has a fast connection elsewhere: pull Tier 1 there, sneakernet on a drive.

Speed tip: `pip install hf_transfer && export HF_HUB_ENABLE_HF_TRANSFER=1`, then
`huggingface-cli download <repo> --include "<pattern>" --local-dir <dest>`.

## Tier 0 — SOFTWARE (only if there is no pre-loaded USB drive)

The tiers below are models only. With no USB, the software has to come down while the
network is up too — models are useless without it. In this order:

```bash
export NVME_ROOT=/path/to/nvme/root   # same value you will pass to setup_box.sh
sudo apt-get install -y ffmpeg git python3.12-venv
curl -fsSL https://ollama.com/install.sh | sh          # ollama itself
pip install -U "huggingface_hub[cli]" hf_transfer      # huggingface-cli itself

# ComfyUI + the six custom node packs (NO ComfyUI-Manager — it phones home)
git clone https://github.com/comfyanonymous/ComfyUI "$NVME_ROOT/ComfyUI"
cd "$NVME_ROOT/ComfyUI/custom_nodes"
git clone https://github.com/kijai/ComfyUI-WanVideoWrapper
git clone https://github.com/kijai/ComfyUI-KJNodes
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite
git clone https://github.com/kijai/ComfyUI-segment-anything-2
git clone https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler   # search GitHub if 404
git clone https://github.com/Fannovel16/ComfyUI-Frame-Interpolation

# Python env. Torch on GB10 (aarch64 + sm_121) is the fragile step: try the cu130 index,
# and if it fails or CUDA is not visible afterwards, follow NVIDIA's DGX Spark ComfyUI
# playbook instead of fighting it (search: "dgx-spark-playbooks comfyui").
python3 -m venv "$NVME_ROOT/venv" && source "$NVME_ROOT/venv/bin/activate"
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
python -c "import torch; print(torch.cuda.is_available())"   # must print True
pip install -r "$NVME_ROOT/ComfyUI/requirements.txt"
pip install fastapi "uvicorn[standard]" httpx pydantic numpy motor

# Editor toolchain (the demo UI runs on the box)
curl -fsSL https://bun.sh/install | bash
cd <repo>/frontend/apps/web && bun install
```

`setup_box.sh` tolerates a pre-existing venv and an already-cloned ComfyUI — running it
after Tier 0 is the intended path.

## Tier 1 — MUST (core live loop, ~45–50 GB total)

```bash
# Brain (agent + vision). Concurrent with the HF pulls below.
ollama pull qwen3-vl:30b                       # ~19 GB   (fallback: qwen3-vl:8b, ~6 GB)

# Wan 2.2 draft video stack — Comfy-Org repackaged files:
#   wan2.2_ti2v_5B_fp16.safetensors      -> comfyui_models/diffusion_models/   ~11 GB
#   wan2.2_vae.safetensors               -> comfyui_models/vae/                ~1.4 GB
#   umt5_xxl_fp8_e4m3fn_scaled.safetensors -> comfyui_models/text_encoders/    ~6.5 GB
huggingface-cli download Comfy-Org/Wan_2.2_ComfyUI_Repackaged \
  --include "*ti2v_5B*" "*wan2.2_vae*" "*umt5_xxl_fp8*" --local-dir /tmp/dl/wan22

# FLUX.2 klein 4B (Apache-2.0) — draft keyframes -> comfyui_models/checkpoints/  ~9–13 GB
# Take black-forest-labs' klein-4B; prefer a ComfyUI fp8 repackage if one exists.
```

## Tier 2 — SHOULD (consent beat + analysis + finish, ~5–8 GB)

```bash
# Person removal (demo beat 3): Wan2.1 VACE 1.3B + wan2.1 VAE   ~4 GB
huggingface-cli download Wan-AI/Wan2.1-VACE-1.3B --local-dir /tmp/dl/vace

# Analysis suite (all small):
huggingface-cli download facebook/sam2.1-hiera-large --local-dir /tmp/dl/sam21   # ~2.4 GB
# InsightFace buffalo_l: run one InsightFace init ONLINE once (auto-downloads ~300 MB)
huggingface-cli download google/siglip2-base-patch16-224 --local-dir /tmp/dl/siglip2
huggingface-cli download nomic-ai/nomic-embed-text-v1.5 --local-dir /tmp/dl/nomic
huggingface-cli download depth-anything/Depth-Anything-V2-Small-hf --local-dir /tmp/dl/depth

# Finish: RIFE 4.9 + SPAN/RealESRGAN x2 (tiny; the Comfy nodes auto-fetch on first use —
# trigger that WHILE ONLINE, see trap below)
```

## Tier 3 — NICE (hero bakery, ~30 GB — only on a fast pipe)

```bash
# Hero i2v: Wan2.2-I2V-A14B fp8 high+low noise (~27–30 GB) + Lightning 4-step LoRAs (~1 GB)
huggingface-cli download Comfy-Org/Wan_2.2_ComfyUI_Repackaged \
  --include "*i2v*14B*fp8*" --local-dir /tmp/dl/wan22h
huggingface-cli download lightx2v/Wan2.2-Lightning --local-dir /tmp/dl/lightning
# Smaller alternative if bandwidth is marginal: QuantStack GGUF Q8 (~15 GB/expert)
# Quality upscale: SeedVR2-3B (~4–7 GB) — SPAN already covers the fast path
```

## SKIP tonight
Fun Camera / Fun Inpaint / Animate 14B (30 GB each), FLUX.2-dev (32 GB **and**
non-commercial), T2V-14B, SeedVR2-7B, Whisper. Nothing in `docs/DEMO_SCRIPT.md` needs them.

## After downloading
Move files into the NVMe layout `registry.json` expects (`comfyui_models/<type>/`, `hf/`),
then run `setup_box.sh`. **Warm-run every workflow once while still online** — several
custom nodes (RIFE, SeedVR2, InsightFace) fetch weights on first use, and the demo is
air-gapped. The smoke test doubles as this warm run for the core loop.

*Repo ids above are best-known as of 2026-08-22; `huggingface-cli download` 404s instantly
on a wrong id — if one 404s, search HF for the model name and paste the error in team chat.*
