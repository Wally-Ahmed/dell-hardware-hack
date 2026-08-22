"use client";

import { useState } from "react";
import { AIChatPanel } from "@/components/rushcut/ai-chat-panel";
import { CastPanel } from "@/components/rushcut/cast-panel";
import { ModelsPanel } from "@/components/rushcut/models-panel";
import { cn } from "@/utils/ui";

const TABS = [
	{ id: "ai", label: "AI" },
	{ id: "cast", label: "Cast" },
	{ id: "models", label: "Models" },
] as const;

type RushcutTabId = (typeof TABS)[number]["id"];

/**
 * Right-hand column hosting the three RushCut panels. All three stay
 * mounted (hidden, not unmounted) so the shared WebSocket keeps feeding
 * jobs/models state while another tab is in front.
 */
export function RushcutPanel() {
	const [activeTab, setActiveTab] = useState<RushcutTabId>("ai");

	return (
		<div className="flex h-full min-h-0 flex-col gap-[0.19rem]">
			<div className="bg-background flex shrink-0 gap-0.5 rounded-sm border p-0.5">
				{TABS.map((tab) => (
					<button
						key={tab.id}
						type="button"
						onClick={() => setActiveTab(tab.id)}
						className={cn(
							"flex-1 rounded-[5px] px-2 py-1 text-xs transition-colors",
							activeTab === tab.id
								? "bg-accent text-foreground font-medium"
								: "text-muted-foreground hover:text-foreground",
						)}
					>
						{tab.label}
					</button>
				))}
			</div>
			<div className={cn("min-h-0 flex-1", activeTab !== "ai" && "hidden")}>
				<AIChatPanel />
			</div>
			<div className={cn("min-h-0 flex-1", activeTab !== "cast" && "hidden")}>
				<CastPanel />
			</div>
			<div className={cn("min-h-0 flex-1", activeTab !== "models" && "hidden")}>
				<ModelsPanel />
			</div>
		</div>
	);
}
