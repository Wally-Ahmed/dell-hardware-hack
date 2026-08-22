"use client";

/**
 * Standalone harness for the three RushCut panels, outside the editor's
 * client-only project bootstrapping — lets the panels be exercised (and
 * their data-testids server-rendered) against the real backend directly.
 */

import { AIChatPanel } from "@/components/rushcut/ai-chat-panel";
import { CastPanel } from "@/components/rushcut/cast-panel";
import { ModelsPanel } from "@/components/rushcut/models-panel";

export default function RushcutDevPage() {
	return (
		<div className="bg-background grid h-screen w-screen grid-cols-3 gap-2 p-2">
			<AIChatPanel />
			<CastPanel />
			<ModelsPanel />
		</div>
	);
}
