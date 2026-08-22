# Endgame prompt for the box agent

*Paste the block below verbatim to the Role A agent when the demo is close. It assumes the
runsheet (`docs/DEMO_RUNSHEET.md`) was already given and compresses to the critical path.*

```
URGENT UPDATE — demo is imminent. The runsheet you were given still governs, but compress to
this critical path. FIRST ACTION, before anything else:

  cd ~/dell-hardware-hack && git pull origin main

This is mandatory — fixes landed after your clone, including one you will hit: the backend
now maps each job type to its workflow template (your generate_shot -> wan5b_i2v). If the
backend is already running, restart it after the pull.

SECOND ACTION — paste this status block to team chat, 60 seconds, no prose:
  phase reached: __ | smoke: A_ B_ C_ | templates in workflows/: __
  services: comfy__ ollama__ backend__ editor__ | models on disk: brain__ wan5b__ klein__
  blockers right now: __

THEN the critical path, strictly in order, each time-boxed. When a box expires, take the
fallback and MOVE ON — do not polish:

1. [20 min, HUMAN at the ComfyUI GUI] wan5b_i2v.json template if not done — runsheet
   Phase 3. TIP: set a real source frame as the image node's default before saving; chat
   requests may not carry an image and the patcher keeps template defaults.
   Then: python3 scripts/smoke_test.py — C must go GREEN. Paste it.
2. [10 min] Backend + editor up (runsheet Phase 4 commands, RUSHCUT_EXECUTOR=comfy).
   Loop check on http://localhost:3000/rushcut-dev: chat "low-angle shot of Dana crossing
   the lobby" -> plan card -> Approve -> real clip lands. Paste "LOOP GREEN ON REAL
   WEIGHTS" + generation time. FALLBACK if the editor fights: demo entirely from
   /rushcut-dev — it is a complete demo surface on its own.
3. [5 min] Policy beat: in chat, request a shot referencing the UNAPPROVED person ->
   job born policy_blocked BEFORE the GPU runs -> approve them in Cast -> regenerate.
   That sequence is demo beat 3. Rehearse it once.
4. [Rest of available time] Generate 2-3 takes of the beat-2 shot, keep the best.
   Stage every fallback asset from docs/DEMO_SCRIPT.md.
5. [Last 30 min, non-negotiable] Lockdown: runsheet Phase 6 — warm-run once, network
   monitor on, confirm silence, box dark. Then ONE full rehearsal of the four beats, timed.

DROP LIST if behind, cut in this order (do not agonize): klein + vace templates -> hero
bakery (say "draft tier" honestly) -> footage shooting (seeded cast: Dana/Marcus/unknown
IS the demo cast) -> editor timeline polish (present from /rushcut-dev).

The pitch opener is already deployed and works offline after a repo pull:
  python3 -m http.server 8912 --directory docs/walkthrough   (or the fly.dev URL pre-lockdown)

Blocked >5 minutes on ANYTHING: paste the exact error + what you tried to team chat and
move to the next item. The conductor is standing by and answers with exact commands.
Language on stage: "policy-enforced, audited, human-signed-off" — never "guaranteed."
```
