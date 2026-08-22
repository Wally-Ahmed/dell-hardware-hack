# Demo Script — four beats, ~4 minutes

*Operator = whoever drives. Presenter talks; operator clicks. Rehearse twice on the real box.
Every beat has a fallback — decide fallbacks BEFORE going on stage, not during.*

## Setup (before judges enter)

- Box: backend `RUSHCUT_EXECUTOR=comfy`, ComfyUI + Ollama up, `scripts/smoke_test.py` green.
- Editor open on the project with pre-ingested footage; Cast panel visible.
- Bakery outputs staged in the bin (hero takes of the same shots the live demo generates).
- Network monitor running on a visible terminal (judges may ask — show it proactively).
- `nemoclaw/egress-policy.yaml` open in a tab for the close.

## Beat 1 — Ingest and the cast (60s)

Drop the footage folder into the watched folder (or run ingest from chat).
**Say:** "It found three people. Two match our approved cast — Dana and Marcus. One is
unknown." Cast panel shows the unknown flagged amber.
**Do:** approve the unknown (or mark remove — pick in rehearsal, removal is the stronger
story if the removal clip is baked).
**Fallback:** ingest already ran; panel simply shows the result. Never ingest live-for-real
the first time on stage.

## Beat 2 — Ask for a shot (90s)

**Do:** select the lobby clip. In chat: *"Give me a low-angle shot of Dana crossing the
lobby."*
**Say:** "The agent doesn't just do it. It shows its plan — which references, which model,
how long — because generative work runs on approval, not on vibes."
**Do:** Approve. A generative clip lands on the timeline, progress fills as the box works
(draft tier: ~1–2 min — keep talking over it: point at the Models panel, memory filling,
nothing leaving the machine).
**Fallback:** if generation stalls, the SAME shot exists pre-baked in the bin — "here's one
we generated earlier" and drag it in. Practice this pivot; it should look intentional.

## Beat 3 — The consent catch (60s)

**Do:** trigger the take that comes back with an extra person (rehearsed seed /
forcePolicyHit).
**Say:** "The model hallucinated a bystander. Nobody unapproved ships — the policy check
re-identifies every face in the output and fixes it." Clip shows policy-blocked → remediated.
**This is the single most important 20 seconds of the demo.**
**Fallback:** pre-baked before/after pair of the same shot.

## Beat 4 — Finish and the close (45s)

**Do:** show the hero-baked version next to the draft; show the upscaled finish.
**Say:** "Draft tier generates live while you work; hero versions bake in the background;
only approved takes get finished."
**Close — the two receipts:**
1. Egress policy on screen: "The agent runs sandboxed. Its allowlist is our backend and the
   local model server. Here's what happens when it tries anything else." (show curl fail)
2. Provenance on a generated asset: model, seed, references, approver. "Nothing left the
   building, and nobody unapproved appears — and we can prove both."

Do NOT say "guaranteed." Say **policy-enforced, audited, human-signed-off**.

## Known truths (if judges push)

- Re-angle: push-ins and lateral moves work; orbits/reverse angles are honest future work.
- It's 2.75–4.7× slower than a desktop 5090 — the pitch is *possible at all, on-prem*, not
  fastest.
- FLUX.2-dev / InsightFace weights are non-commercial: flagged, permissive swaps named.
