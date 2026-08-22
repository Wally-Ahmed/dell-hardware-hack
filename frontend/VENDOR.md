# Vendored: OpenCut @ pre-rewrite

Upstream: https://github.com/OpenCut-app/OpenCut, tag `pre-rewrite`
(commit 238750c, 2026-05-18 — the last commit before the ground-up rewrite).
License: MIT (upstream LICENSE retained in this directory).

**This is a snapshot, not a fork we track.** Upstream is mid-rewrite with its
API surface unbuilt and contributions paused; we deliberately do not chase
main and never upstream. Bake-off evidence and the losing candidate are in
docs/PLAN.md §4 and HANDOFF.md.

## Working on it
- Toolchain: bun 1.4 (`npm i -g bun` if missing). Editor app: `apps/web`.
  `cd frontend/apps/web && bun install && bun run dev` → :3000.
  Boot needs a dummy `.env.local` — copy `.env.local.example` (postgres/
  redis/auth values never block the editor).
- Note: `nvm use` switches bun out of PATH — use bun's absolute path after nvm.

## First files for our four panels (Role C)
1. `apps/web/src/app/editor/[project_id]/page.tsx` — mount AIChatPanel /
   CastPanel / ModelsPanel as ResizablePanel entries.
2. `apps/web/src/panels/layout.ts` + `src/editor/panel-store.ts` — register
   panel sizes/visibility.
3. `apps/web/src/timeline/types.ts` (element union, ~line 166) +
   `src/timeline/components/timeline-element.tsx` — add GenerativeElement
   { jobId, model, refs, prompt, seed, progress } + its render branch.
   Backend URL: add NEXT_PUBLIC_BACKEND_URL to `src/env/web.ts`.

Contract to speak: docs/api.md (WebSocket job frames, whole-object updates).
