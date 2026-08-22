# NemoClaw sandbox — box-side setup (GB10)

Runs the RushCut agent inside an egress-locked sandbox so "nothing leaves
the building" is enforced by policy, not by promise. Config only — nothing
in this directory installs anything on your laptop.

**Time-box: 90 minutes.** Start the clock at step 1. If the sandbox is not
demoing by then, stop and use the fallback at the bottom — the agent and its
tools are identical either way; only the enforcement demo differs.

## 1. Install NemoClaw (one command)

From the NVMe copy of the USB drive (never run from the drive itself;
installer and wheels are on the drive per `MANIFEST.md` — no downloads, the
box has no internet):

```bash
sudo <nvme>/nemoclaw/install.sh
```

## 2. Launch OpenClaw inside OpenShell with this policy

From the repo root on the box:

```bash
openshell --policy nemoclaw/egress-policy.yaml -- openclaw
```

OpenShell loads `egress-policy.yaml` (loopback :8000 and :11434 only, no
DNS, default deny) and everything OpenClaw spawns inherits it.

## 3. Point inference at local Ollama

Inside the sandbox, set OpenClaw's inference endpoint to `inference.local`,
which NemoClaw maps to the loopback Ollama the policy allows:

```bash
export OPENCLAW_INFERENCE_URL=http://inference.local:11434/v1
export RUSHCUT_OLLAMA_URL=http://127.0.0.1:11434/v1
export RUSHCUT_BACKEND_URL=http://127.0.0.1:8000
export RUSHCUT_BRAIN=qwen3-vl:30b
```

## 4. Prove the air gap (the demo beat)

Inside the sandbox:

```bash
curl -s --max-time 3 http://127.0.0.1:8000/health   # works
curl -s --max-time 3 https://example.com            # refused — no DNS, no route
```

## Fallback (sandbox not up in 90 minutes)

Run the loop directly against Ollama — same tools, same tiers, same
consent gates; you just skip the sandbox segment of the demo:

```bash
cd <repo-root>
python -c "
import asyncio
from backend.agent.loop import AgentLoop
loop = AgentLoop()
print(asyncio.run(loop.turn('list the cast'))['reply'])
"
```

(Or just mount the router — `backend/agent/README.md` — and drive it from
the AI panel; the no-cloud story then rests on the network monitor from
CLAUDE.md §6 instead of sandbox enforcement.)
