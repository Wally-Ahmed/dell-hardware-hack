# An AI-Native Editor for Professional Filmmakers

*Build plan, 22 August 2026, ~13:45 EDT. Demo tonight. Team of three to five, working on separate branches. Open source, GPL-3. One NVIDIA GB10. MongoDB for state, NVIDIA NemoClaw as the agent harness.*

---

## 1. What We Are Building, and Why It Is Different

The product is a professional video editor in which an AI agent sits beside the editor rather than behind a menu. The human keeps the timeline, the taste, and the final say; the agent handles the parts of filmmaking that are currently impossible or ruinously expensive — recreating a shot from an angle nobody covered on the day, altering what happened inside a scene, inserting a character who was never on set, and building new scenes from actors already present in the footage. Each of those exists today as a research demo or a cloud service. None exist inside an editor a working professional would cut on, and none run on a machine you own.

That last point is the strategic one. Everything runs on a single NVIDIA GB10 — aarch64 Linux, 128 GB unified memory, ~273 GB/s — with no cloud API of any kind. This is commercial, not ideological. Unreleased footage is the most legally radioactive asset a production owns, and Netflix's published generative-AI guidelines for partners now require that tools not store, reuse, or train on production data, that work happen in a secured environment, and that generated material be disclosed. Our architecture satisfies those by construction rather than by promise. That is the enterprise wedge, and it is worth saying in those words during the pitch.

The feature that makes the pitch memorable, and that we protect above all others when time runs short, is **background character control**. Every person appearing in a shot — foreground or deep background, real or generated — is detected, clustered into an identity, and assigned a policy: approved, unknown, or remove. Generated output is re-checked against that registry before it can land in the cut. It is simultaneously a creative problem (the extra who pulls focus), a legal one (background performer consent, now governed in detail by the 2023 and 2026 SAG-AFTRA agreements), and a practical one (the model that hallucinates a crowd into your empty lobby).

One discipline about language that matters more than it sounds: we do **not** say "guaranteed." Published research shows concept erasure in diffusion models is circumventable — learned embeddings recover supposedly erased concepts without touching model weights, and the authors call the methods brittle. Negative prompting is steering, not a gate. What we can honestly claim is **policy-enforced, audited, and human-signed-off**. In front of professionals that is both true and more credible than an absolute they know cannot hold.

---

## 2. Roles and Branches: How Five People Build This in Parallel

This is the section that decides whether five people move five times as fast or spend the last hour resolving conflicts. The organizing principle is not "split by feature" but **split by directory ownership**, so two people are structurally incapable of editing the same file. Every role owns a disjoint set of paths on its own branch, and the shared contract lives on `main` where nobody edits it after 13:30.

The sequence matters absolutely. `main` receives the **contract commit first** — `docs/api.md`, `backend/models/registry.json`, the MongoDB collection schemas, the job-state enum, and a mock FastAPI server returning canned job results. Only after that lands does anyone branch. This is the highest-leverage half hour of the day: with the contract fixed, four roles build at full speed while the GB10 is still being provisioned. Without it, every role serializes behind the box and a team of five delivers like a team of one.

| Role | Branch | Owns exclusively | First deliverable |
|---|---|---|---|
| **A — Box & Models** | `box` | `workflows/`, `scripts/`, the GB10 itself | Klein image + Wan 5B clip through the ComfyUI HTTP API |
| **B — Backend & Jobs** | `backend` | `backend/app.py`, `backend/jobs/`, `backend/models/`, `backend/render/` | Job queue + WebSocket progress against the mock |
| **C — Editor UI** | `editor` | `frontend/` (everything) | Fork building, timeline rendering, four panels stubbed |
| **D — Ingest & Cast** | `ingest` | `backend/ingest/`, `backend/db/` | MongoDB collections + person clustering on one clip |
| **E — Agent & NemoClaw** | `agent` | `backend/agent/`, `nemoclaw/` | NemoClaw sandbox reaching the backend, one tool round-trip |

With four people, E folds into B. With three, D absorbs E and C takes the render path. Role A works on the GB10 directly rather than in a Codespace, because their job is the box; everyone else works in their own Codespace, which is also why per-user Codespaces suit this split — four dev servers, no port collisions.

**Merges go to `main` on a clock: 14:30, 15:30, 16:30.** Short-lived branches merged often is the entire point; a branch that lives six hours is a fork with extra steps. Each merge is a fast-forward or a small rebase, whoever breaks `main` fixes it immediately rather than continuing on their branch, and nobody force-pushes `main`. If a role needs something outside its territory, they ask the owner — a thirty-second conversation beats a merge conflict at 17:00.

There is exactly one genuine cross-cutting seam, and naming it now is how we avoid discovering it at 16:00: the **generative clip** touches the editor (rendering and progress), the backend (job lifecycle), and ingest (policy check on completion). That contract — the precise JSON shape of a job and its state transitions — goes into `docs/api.md` in the first thirty minutes and changes only by agreement between roles B, C, and D.

---

## 3. Three Corrections to the Original Brief

**DaVinci Resolve cannot run on our hardware at all.** Blackmagic ships Resolve for Windows x64, Windows-on-ARM, macOS, and Linux **x86_64 only** — there is no aarch64 build and none announced, so it cannot run on a GB10 under any license. Three further blockers stack behind that: external scripting has been Studio-only since 19.1, the UIManager that draws custom panels was disabled in the free edition in the same release, and Resolve Free on Linux cannot decode or encode H.264/H.265 at all. Resolve survives here only as an export target for a colorist's x86 box.

**Forking a C++/Qt NLE is a multi-day job, and the best candidate is better than expected.** Kdenlive is genuinely well-suited long term: GPL-3, ~350 commits a quarter, packaged for Ubuntu 24.04 arm64, and it already contains three things we need — `MainWindow::addDock()` makes a panel cheap, `AbstractTask`/`TaskManager` already reports background job progress into the media bin (our generative-clip infrastructure), and `AbstractPythonInterface` is a working venv and dependency manager already backing Whisper and SAM2 (most of a model-manager panel). It also has native C++ OpenTimelineIO in-tree. **For a serious version of this product, Kdenlive is the right base.** For six hours on aarch64, it is not.

**The Codespace has no GPU.** It is a development box for the editor and backend. Inference, ingest, and the demo run on the GB10. Anything touching a model is built against a mock and validated on the box. One hardware detail worth knowing before it costs an hour: the GB10's Blackwell GPU only produces a display framebuffer when a monitor is detected — bring a real display or a 4K HDMI dummy plug.

---

## 4. The Editor: A Thirty-Minute Bake-Off, Then Commit

You chose to fork OpenCut, and for a six-hour build that instinct is right — a TypeScript and React editor is the only kind whose extension surface we can absorb in an afternoon. But two facts should shape how we approach it.

OpenCut is **mid-rewrite**. The project announced a ground-up rebuild in May 2026, merged it to main in July, and is moving to a Rust core. Its planned Editor API, plugin system, headless rendering, and MCP server are documented intent rather than shipped code, outside contributions are paused while the architecture settles, and the contributing guide currently marks preview enhancements and export as "avoid for now." Its 65,000 stars are mindshare, not maturity. **The mitigation is non-negotiable: fork the last stable pre-rewrite branch, do not chase main, never try to upstream anything.** We are taking a snapshot, not joining a project.

The alternative is **OpenChatCut** — AGPL, local-first, React 19 and Vite, and startlingly close to what we are building. It already has a multi-track timeline, immutable timeline state with a command layer, and the exact agent interaction model we independently designed: `begin_edit_session` creates an isolated draft, the agent edits the draft while the working project stays untouched, the user previews, and `review_edit_session` applies or rejects **as a single atomic undo step**. It uses stable identifiers rather than ordinal positions specifically to prevent state drift. AGPL is compatible with our open-source release. Its own documented gap is the lesson: external agents over MCP currently bypass the proposal layer and write straight to the working timeline. We must not repeat that.

So Role C's first thirty minutes is a bake-off, not a decision made now on incomplete information. Clone both, run both, pick on evidence — does it build in the Codespace, does the timeline render, can we add a panel. **Commit by 14:15 and do not revisit.** If both fight back, Plan B is a minimal custom React editor with a media bin, one video track, preview, and our panels: less impressive, fully under our control.

Whichever wins, four additions make it ours. The **AI panel** is a chat thread aware of the current selection and playhead, rendering agent suggestions as proposal cards to preview, apply, or discard. The **Cast panel** lists detected people with policy state and reference crops. The **Models panel** shows each model's status with a memory bar and pin toggle — what makes the local-only story visible rather than merely claimed. The **generative clip** is a timeline clip type carrying job id, model, references, prompt, and seed, showing progress in place and landing in the bin on completion. A project switcher makes it multi-project.

---

## 5. The Agent: NemoClaw as the Harness

NemoClaw is a better fit than I expected, and one of its properties is a genuine gift to this specific pitch. It is NVIDIA's open-source reference stack for running agents inside OpenShell sandboxes, announced at GTC 2026, licensed **Apache-2.0**, and — critically — **DGX Spark is one of its primary tested platforms.** That is our exact box. It supports OpenClaw (the default, and already installed on this machine), Hermes, and LangChain Deep Agents Code as harnesses, and it connects to local inference providers through `inference.local`, so we point it at Ollama or vLLM serving `qwen3-vl:30b` on the same machine and no token ever leaves the box.

The gift is the **declarative egress policy**. NemoClaw runs the agent in a sandbox where OpenShell blocks unapproved destinations, and the policy is YAML we control. That converts our central claim from an assertion into a demonstration: allowlist exactly one destination — our FastAPI backend on localhost — deny everything else, then show the policy on screen and show the agent unable to reach the internet. "Trust us, it's air-gapped" becomes "here is the policy, and here is what happens when the agent tries." For an audience that may be running a network monitor, that is worth more than any slide.

The model choice is dictated by physics rather than preference. At 273 GB/s the time to stream weights dominates, so **mixture-of-experts with few active parameters is the only viable shape**: measured on this class of hardware, a 30B MoE with ~3B active runs around 89 tokens/second while a 32B dense model manages about 10.7 — an eight-fold gap that is purely the bandwidth wall. `Qwen3-VL-30B-A3B-Instruct` is Apache-2.0, roughly 19 GB, sees and calls tools, and is the right default. Prefill is compute-bound and cheap at roughly 1,900 tokens/second, so contact sheets and long shot lists cost us little; generation is what costs.

Two design rules come from the prior art and should be treated as requirements. **Cap the tool count between twenty and thirty and never expose arbitrary code execution.** Tool-selection accuracy has been measured collapsing from about 95% with a focused toolset to 71% with a large one loaded, and the mature DaVinci Resolve integration ships thirty-four compound tools versus three hundred and forty-one granular ones precisely because of this. On code execution the Blender ecosystem ran the experiment for us: the popular community server exposes raw Python and warns in its own README to save your work first, while Blender's official server is deliberately small and does no more than necessary. We take the vendor's side. And **reference everything by stable identifier, never ordinal position** — not "the third clip" but a clip id, because ordinals drift the moment anything changes.

Permissions are tiered by reversibility, not by feature. Cheap reversible actions the agent performs directly. Structural edits are *proposed*: the agent opens an edit session, works in an isolated draft, the human previews, and it applies as **one undoable command** or is rejected — with no path, internal or external, reaching the working timeline without passing through a session. Anything generative requires a plan shown first. **Time-box the NemoClaw integration to ninety minutes**; it is an early-preview product and the fallback is the hand-written 150-line tool loop straight against Ollama, which loses the sandbox demo but not the product.

---

## 6. MongoDB: The State Layer

MongoDB replaces SQLite, and the document model is genuinely the better fit here rather than merely a constraint to satisfy. A `person` document naturally holds nested reference crops, multiple embeddings, policy history, and consent records in one place — no join tables, no schema migration when we add a field at 16:00. Collections: `projects`, `media`, `shots`, `people`, `scenes`, `generations`, `notes`. `mongod` runs locally on the box bound to localhost only.

**On vector search, make the pragmatic call and state it plainly.** MongoDB now offers native full-text and vector search on self-managed Community Edition, which is the right long-term answer, but it deploys as a separate search-node process and betting tonight's demo on getting that running on aarch64 in an afternoon would be reckless. For tonight: store embeddings as plain arrays in the documents and do brute-force cosine similarity in numpy. At demo scale — hundreds to a few thousand vectors — that is microseconds, and it removes an entire category of risk. Role A can stand up a proper search node later if the afternoon goes well.

The `people` collection is the heart of the product. Each document is a clustered identity with role, policy, face embeddings, and reference crops for face, body, and wardrobe. This is what makes a character reusable: once an actor is ingested, we can generate new shots of them because we hold the references a multi-reference model needs. "Create a new scene with a character from existing footage" is not a separate feature — it falls out of this collection existing.

The `generations` collection enforces provenance: model, precision, prompt, seed, references, parent asset, and job id for every generated asset. Partly good engineering, since it makes "regenerate with one change" tractable, but mostly it is the consent story made auditable. The chain we want to show for any delivered frame runs consent record → references used → model and seed → parent asset → policy-check result → human approver and timestamp. Multi-project means a `projectId` on every document from the first write — nearly free today, painful to retrofit tomorrow.

---

## 7. The Backend, the Job Queue, and ComfyUI

The backend is a FastAPI service that is the single point of truth for everything the editor and the agent can do. Both the human clicking a button and the agent calling a tool go through the same command layer, so every action is logged, attributed, and undoable. The Resolve MCP ecosystem is the cautionary tale: the most mature editing-agent integration available has **no undo at all**, because Resolve's scripting API cannot reverse operations, and no ability to block destructive ones — it can warn, not prevent.

Generative work is slow and bursty, so the backend owns a job queue and pushes progress over a WebSocket. A generate request returns a job id immediately; the timeline clip renders a progress state and updates as the job advances. This is what lets a five-minute render coexist with an editor who keeps working — the same pattern Adobe shipped with Generative Extend. The backend does no inference: it composes parameters into saved ComfyUI workflows, posts them, polls, and fetches outputs. Zero inference code in our repo.

ComfyUI is GPL-3, compatible with our GPL-3 release. Each capability is a saved workflow in `workflows/`, built in priority order: `klein_keyframe_multiref` and `wan5b_i2v` are the core demo loop and must exist first, then `vace_inpaint_person` and `seedvr2_upscale`. **Four box-specific gotchas will each cost an hour if discovered late, so Role A should know them before starting.** ComfyUI has a unified-memory double-allocation bug on this hardware — safetensors are mmap'd into RAM then copied into "VRAM" which is the same RAM, effectively halving usable memory to about 64 GB — so run with `--disable-mmap` and budget 2× model size at load. Pass `--disable-api-nodes` to force fully offline operation and disable the paid cloud nodes. ONNX Runtime has no aarch64 wheel on PyPI, so DWPose and ControlNet preprocessors silently fall back to CPU and look like a mysterious ten-fold slowdown. And never use `--gpu-only`; it fights the unified-memory fabric.

Do **not** install ComfyUI Manager. It phones home, and there was a documented incident where desktop telemetry continued after users explicitly disabled it. Pin exact custom-node commits instead. Also set `HF_HUB_DISABLE_TELEMETRY=1` alongside `HF_HUB_OFFLINE=1`, because HuggingFace Hub fires telemetry on downloads independently of anything ComfyUI does.

The single riskiest item of the day lives here: if ComfyUI does not come up on aarch64 with these nodes and weights, there is no demo. Role A does nothing else until a klein image and a Wan 5B clip have both returned through the HTTP API.

---

## 8. The Model Manager and the 128 GB Budget

At 273 GB/s, streaming weights dominates the cost of using a model, which makes quantization the primary performance lever rather than a reluctant compromise. Never load bf16 when FP8, int8, or GGUF-Q8 exists, and prefer few-step distilled models. One counterintuitive finding worth knowing: NVFP4 does **not** speed up video diffusion on this hardware — it is weight-only and dequantizes before matmul, and video transformers are compute-bound, so measured times were 18.0s FP8 versus 19.1s NVFP4 for the same clip. It does help LLM decode, which is bandwidth-bound. Use FP8 for diffusion, NVFP4 for the language model.

The manager is driven by `registry.json` generated from the USB manifest: task, path, precision, footprint, load time, license, tier, and one human-readable line describing what each model is best for — the field the agent reads when it chooses. A realistic simultaneous budget is roughly 14–20 GB for the OS and editor, 19–22 GB for the resident language model plus 4–8 GB of KV cache, 6–9 GB for the analysis suite, and 20–32 GB for one generative model, leaving reserve. That fits with slack. What does not fit is a language model plus a generative model plus a large upscaler concurrently, so **upscaling is scheduled as an exclusive stage** with a `POST /free` on the generator first.

Behavior is three-tier: *pinned* models never evicted (the brain, segmentation, detection, depth) because they are what makes the app feel alive; one *hot-swappable* generative model under LRU; and *exclusive* stages that take a global lock. Pre-warm on project open behind a splash screen, because JIT and CUDA-graph capture costs around 25 seconds. Set `PYTORCH_NO_CUDA_MEMORY_CACHING=1` and disable pinned memory — on a unified pool, pinning locks pages for no benefit and a CPU-side staging copy is pure waste.

The same registry feeds the agent's `list_models` tool and the Models panel. The agent gets an honest view of what is cheap and expensive; the audience watches memory fill and drain in real time. For a product whose claim is that it runs entirely on the machine in front of you, a live memory bar beats any slide.

---

## 9. Ingest: Turning Footage Into a Cast

Ingest converts raw media into everything else the system knows. Scene detection cuts footage into shots, SAM2 tracks each person, faces are detected and embedded per track, and embeddings are clustered into identities across all footage *and* any supplied stills — which is how a headshot the production already has anchors a person appearing in dailies. For each identity the pipeline picks the sharpest, most frontal, best-lit frames, crops face, body, and wardrobe references, and builds a contact sheet for a human to name and approve.

**Face-only clustering is the wrong primitive, and this is the most important technical finding of the research.** The literature on video person-clustering argues directly that prior work focused too narrowly on faces while ignoring appearance, voice, and editing structure — and background extras are exactly the population turned away, out of focus, or small in frame. A large fraction of background tracks will have no usable face at all. The body and wardrobe crops are not a nice-to-have; they carry identity when the face is unavailable.

Two failure modes deserve engineering rather than hope. **Occlusion causes identity switches** — running SAM2 as parallel single-object trackers degrades badly when people cross, and the fixes that work without retraining are memory-strategy changes, so budget for one rather than assuming the tracker holds. **Wardrobe changes break cross-clip clustering**, because cloth-changing re-identification remains unsolved, so identity linkage across shoot days will have real error. Plan for clustering good enough to *propose* and never good enough to *decide*.

That yields the rule that matters most: **every unresolved track is surfaced to a human, never silently dropped.** A silently-dropped track is a person who ships without consent. Make merging, splitting, and correcting clusters fast, because correction is the normal case. Two license notes for Role D: **InsightFace's pretrained models are non-commercial research only** even though its code is MIT, and **Ultralytics YOLO is AGPL**. Both are fine for a demo tonight; for release, AdaFace (MIT) and RT-DETR (Apache-2.0) are the drop-in replacements. Flag it in the pitch rather than being caught by it. There is also a fairness dimension worth internalizing: NIST's evaluations document widespread demographic differentials in face recognition false-positive rates, which means a filter that removes "unapproved" people misfires unevenly — building that into a rights-enforcement product without measuring it would be a real failure.

---

## 10. Background Character Control

Only people in the registry with policy `approved` may appear, foreground or background. An unknown face in source footage asks the human. An unknown face in generated output triggers `enforce_cast_policy`, which re-runs identification on the output and either inpaints the person out, regenerates with strengthened constraints, or rejects the take.

Enforcement runs on the **output**, not the prompt, and the research settles why. Concept-erasure methods have been shown circumventable, with learned embeddings recovering supposedly erased concepts without modifying weights, and the authors describe them as brittle. Negative prompting carries a specific cost in video, where effort spent avoiding unwanted elements degrades frame-to-frame consistency. Detect-and-remediate is slower, less elegant, and the only defensible version.

Two asymmetries belong in the gate. **False negatives are catastrophic and false positives are cheap** — one missed face ships, one spurious flag costs a click — so tune for recall and route ambiguity to a human. This is the inverse of how face recognition is normally tuned and must be deliberate. And detection runs across *all* frames, not keyframes, because a person can enter for eight frames and leave. For removal, **Netflix VOID** is the notable 2026 option: Apache-2.0, and it removes not just the person but their physical consequences — shadows, disturbed water, held objects — which matters because removing someone while leaving their shadow is an instantly visible failure on a professional monitor. It caps at 197 frames and 384×672 natively, so expect chunking plus an upscale pass. Wan VACE inpaint remains the simpler Apache-2.0 fallback for static-camera shots. Avoid ProPainter and MatAnyone: both are strictly non-commercial.

The real-world dimension strengthens the pitch if described accurately. The 2023 SAG-AFTRA agreement requires consent before creating a digital replica, with at least 48 hours' notice, clear and conspicuous and separately signed rather than buried in terms, tied to a reasonably specific description of use for an identified project — no blanket authorization. The 2026 agreement, ratified in June and running to 2030, adds further provisions. And **EU AI Act Article 50 became applicable on 2 August 2026 — three weeks ago** — placing machine-readable marking of synthetic output on the **provider** of the generating system, which is us, not only our customers. Worth knowing before release even though it will not be built tonight. In the pitch, say plainly that this records who consented to what and makes the chain auditable, and leave legal conclusions to the people who make them.

For tonight the demonstrable version is: a Cast panel with approve/unknown/remove, one generation that returns an unapproved face, and the system catching and fixing it on screen. That single moment is worth more than any three other features here.

---

## 11. Generative Shot Creation and Finishing

The pipeline runs in explicit stages — analyze, gather references, keyframe, motion, policy check, finish, place — rather than one opaque call, which is what lets the agent show a plan, the user intervene at a boundary, and a failed policy check trigger a targeted fix. The good news on licensing is substantial: **the entire Wan 2.2 family is Apache-2.0**, including the 14B image-to-video and text-to-video models, VACE, Fun Inpaint, Fun Camera, and Animate, and the Lightning four-step distillation LoRAs are Apache-2.0 as well. `FLUX.2-klein-4B` is also Apache-2.0. But **FLUX.2-dev and klein-9B are non-commercial** — usable tonight, flagged for release, with Qwen-Image-Edit-2511 (Apache-2.0, up to three references) as the permissive alternative.

Recalibrate the clock honestly: this hardware measures **2.75× to 4.7× slower than an RTX 5090** on diffusion work. Whatever timing you have in mind from a desktop GPU, multiply it. That single fact is why the hero bakery has to start early rather than "when we get to it."

Re-angling is the most ambitious capability and most likely to disappoint, and the research is unusually specific about how it fails. **Rotation is fundamentally harder than translation** — rotational commands leak large translational drift while translational commands barely leak the other way, so "push in" mostly works and "orbit around the subject" drifts sideways. **Horizontal moves are far better than vertical**, so crane and boom are markedly worse than dolly and truck. Beyond a control threshold models exhibit motion-mode collapse, abruptly cutting between viewpoints instead of moving smoothly — which reads as a jump cut. Face coherence drifts after four to five seconds. And critically, **camera control should never be exposed as a text prompt**: geometric conditioning extracts far more motion at minor quality cost. What to promise: modest push-in and pull-out, lateral truck, reframing, small parallax on a static camera. What not to promise: true reverse angles on dynamic scenes, sustained orbits, vertical crane, or anything past two to three seconds in one pass.

Finishing is disproportionately cheap and separates a demo from something that belongs in a cut: upscale, interpolate, then match grain and grade to surrounding footage. That last step is most often skipped and does the most work, because generated footage that is too clean and too stable reads as fake even when its content is perfect. SeedVR2 (Apache-2.0) is the quality upscaler but is an overnight-class operation here — budget roughly 50–90 minutes for a five-second 720p to 4K pass — so **SPAN is the pragmatic fast path**, measured around six times faster than Real-ESRGAN at similar perceptual quality. Chunking with overlap is mandatory rather than optional, because naive frame-by-frame upscaling produces shimmer more objectionable than the original resolution. RIFE (MIT) handles interpolation, and doubles as a throughput tool: generating fewer frames and interpolating up is often faster than generating at the target rate. Generate at 480–720p, upscale only approved takes, and hold 720p as the floor for anything destined for the timeline.

---

## 12. The Day: Sequencing and the Cut Line

It is roughly a quarter to two and the demo is this evening, leaving about four hours of build time including two rehearsals. State that number to the whole team at the start, because the common failure in a build like this is not technical — it is spending the last hour integrating components each individually finished and never once run together.

Two clock moments are non-negotiable. **The hero bakery starts by 14:30** — given the 2.75–4.7× hardware penalty, hero versions of the demo shots need every minute of head start, and this single decision determines whether the demo looks finished or looks like a prototype. **The integration checkpoint is 15:30**: select a clip, ask chat for a new shot, watch a generative clip appear, progress, and land policy-checked. If that loop is not working at 15:30, stop adding features and defend it.

The cut line, in order. Ship: the editor, the chat panel, the agent loop, one image pipeline, one video pipeline, the cast panel, the generative clip, and `enforce_cast_policy`. Cut in this sequence if needed: OpenTimelineIO export, then the NemoClaw sandbox in favor of the direct Ollama loop, then the live bakery in favor of pre-baked assets, then `reangle_shot`, then `remove_person`, then Models panel polish. Nothing above the line is sacrificed to save something below it, and whoever notices we are behind says so at 15:30, not 17:30.

---

## 13. Verification, the Air Gap, and the Demo

The air gap is a claim we will be asked to prove, so it gets verified rather than assumed. Export `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `HF_HUB_DISABLE_TELEMETRY=1`. Disable Ollama and ComfyUI update checks, run ComfyUI with `--disable-api-nodes`, do not install ComfyUI Manager, and carry no frontend analytics. Then run a network monitor against the box and confirm silence — far better we find something than a judge does. NemoClaw's egress policy is the belt to that suspenders, and it is the version the audience can actually see.

Functional verification is one script, `scripts/smoke_test.py`, pushing a keyframe image, a video clip, and a face-identification pass end to end through the HTTP API. Write it early, run it often, treat it as the definition of "the system works." A green smoke test at 16:00 is worth more than any amount of confidence about individual components.

The demo runs in four beats. Footage lands in the watched folder and the agent reports what it found — three people, two matching approved cast, one unknown. The unknown is approved, a new shot is requested in plain language, the agent shows its plan with references and model and estimated time, and on approval a generative clip appears, progresses, and lands policy-checked. A hero-baked version is shown alongside the upscaled finish. The close returns to the consent registry, and to the egress policy: nothing left the building, and nobody unapproved appears.

Rehearse twice, on the real box, with the real footage. Rehearsal is not about the script — it surfaces the missing asset, the model that needs thirty seconds to load, and the panel that renders wrong at projector resolution. Those are what end demos, and they are only ever found by running the whole thing start to finish before it counts.

---

## Appendix: Repository and Codespace Setup

The repository is `Wally-Ahmed/dell-hardware-hack`, public from the first commit, GPL-3, with the two existing local commits pushed. Public from the outset means discipline about what lands: the `.gitignore` already blocks model weights, media, runtime state, and environment files, and no footage of real people is ever committed.

A `.devcontainer/devcontainer.json` provisions Node 20, Python 3.12, ffmpeg, MongoDB tools, and git, with a `postCreateCommand` that installs the toolchain so every teammate's Codespace is identical. I drive the primary Codespace over `gh codespace ssh`; each teammate creates their own from the same repo, which is what makes the five-branch split work cleanly.

The assistant in every Codespace is pinned to Fable at maximum effort through a committed `.claude/settings.json`, so it applies to the team rather than one laptop. The same memory tooling as this machine goes in: `claude-mem`, MemPalace, graphify, and the native auto-memory directory.

One step I cannot do for you: authenticating Claude Code inside the Codespace requires an interactive login. Run `claude` in the Codespace terminal once and follow the flow. Everything after that I can drive.
