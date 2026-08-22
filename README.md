# An AI-Native Editor for Professional Filmmakers

A professional video editor where an AI agent works *beside* the editor rather than behind a
menu — recreating shots from angles nobody covered on the day, altering what happened inside a
scene, inserting characters who were never on set, and building new scenes from actors already
present in the footage.

**Everything runs locally on one NVIDIA GB10.** No cloud APIs, no telemetry, nothing leaves the
building. That is not an ideological position — unreleased footage is the most legally
radioactive asset a production owns, and a tool that guarantees locality is the only kind a lot
of this market can legally use.

## The differentiating feature: background character control

Every person appearing in a shot — foreground or deep background, real or generated — is
detected, clustered into an identity, and assigned a policy: `approved`, `unknown`, or
`remove`. Generated output is re-checked against that registry before it can land in the cut.

It is simultaneously a creative problem (the extra who pulls focus), a legal one (background
performer consent, now governed in detail by the 2023 and 2026 SAG-AFTRA agreements), and a
practical one (the model that hallucinates a crowd into your empty lobby).

We say **policy-enforced, audited, and human-signed-off** — never "guaranteed." Concept erasure
in diffusion models is demonstrably circumventable, and an absolute claim in front of
professionals is one they know cannot hold.

## Stack

| Layer | Choice |
|---|---|
| Editor | OpenCut fork (React/TS) — see `docs/PLAN.md` §4 for the bake-off against OpenChatCut |
| Backend | FastAPI + WebSocket job queue |
| Agent harness | **NVIDIA NemoClaw** (Apache-2.0) — sandboxed agent, declarative egress policy |
| Brain | `qwen3-vl:30b` via Ollama — MoE, vision + tool calling |
| Execution | ComfyUI over localhost HTTP — zero inference code in this repo |
| State | **MongoDB** — projects, media, shots, people, scenes, generations, notes |
| Hardware | NVIDIA GB10 · aarch64 · 128 GB unified · ~273 GB/s |

NemoClaw's declarative egress policy is what turns our air-gap claim into something
demonstrable: allowlist exactly one destination — our backend on localhost — deny everything
else, then show the agent failing to reach the internet.

## Getting started

**Read `docs/ROLES.md` first.** It tells you which branch you own and which directories are
yours. Then read `docs/api.md` — the contract every role builds against.

```bash
git clone https://github.com/Wally-Ahmed/dell-hardware-hack
cd dell-hardware-hack
git checkout <your-branch>          # box | backend | editor | ingest | agent

# Build against the mock — do not wait for the GB10
uvicorn backend.mock.app:app --reload --port 8000
```

Development happens in GitHub Codespaces (each teammate gets their own). The Codespace has no
GPU — it is the dev box. The GB10 is the demo box.

## Docs

| File | What |
|---|---|
| `docs/ROLES.md` | Roles, branches, directory ownership, merge protocol, clock, cut line |
| `docs/api.md` | The contract — job states, assets, agent tools, MongoDB collections |
| `docs/PLAN.md` | Full architecture and reasoning, including what we rejected and why |
| `CLAUDE.md` | Original planning handoff |
| `backend/models/registry.json` | Model registry with licenses and `bestFor` lines the agent reads |

## Licensing

This project is **GPL-3.0**. Two model licenses are flagged in `registry.json` as demo-only and
must be swapped before any commercial release: **FLUX.2-dev** (non-commercial) and
**InsightFace** pretrained weights (non-commercial research only — the code is MIT, the weights
are not). Qwen-Image-Edit-2511 and AdaFace are the permissive replacements. The entire Wan 2.2
family is Apache-2.0.
