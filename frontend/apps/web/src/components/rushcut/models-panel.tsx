"use client";

import { useCallback, useEffect, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	fetchModelBudget,
	fetchModels,
	pinModel,
	type ModelBudget,
	type ModelState,
	type RushcutModel,
} from "@/lib/rushcut/api";
import { useRushcutSocket, useRushcutStore } from "@/lib/rushcut/ws";
import { cn } from "@/utils/ui";

const STATE_DOT: Record<ModelState, string> = {
	idle: "bg-muted-foreground/40",
	loading: "bg-amber-500 animate-pulse",
	resident: "bg-emerald-500",
	evicting: "bg-muted-foreground/40 animate-pulse",
};

export function ModelsPanel() {
	const { connected, models: liveModels } = useRushcutSocket();
	const [fetchedModels, setFetchedModels] = useState<RushcutModel[]>([]);
	const [budget, setBudget] = useState<ModelBudget | null>(null);
	const [offline, setOffline] = useState(false);
	const [pinBusyId, setPinBusyId] = useState<string | null>(null);

	const models = liveModels.length > 0 ? liveModels : fetchedModels;

	const refresh = useCallback(async () => {
		try {
			const [modelList, budgetInfo] = await Promise.all([
				fetchModels(),
				fetchModelBudget(),
			]);
			setFetchedModels(modelList);
			setBudget(budgetInfo);
			setOffline(false);
		} catch {
			setOffline(true);
		}
	}, []);

	// Initial load + reload whenever the socket (re)connects.
	useEffect(() => {
		refresh();
	}, [refresh, connected]);

	// Models frames signal load/evict activity — usedGb moved with them.
	useEffect(() => {
		if (liveModels.length === 0) return;
		fetchModelBudget()
			.then((budgetInfo) => {
				setBudget(budgetInfo);
				setOffline(false);
			})
			.catch(() => setOffline(true));
	}, [liveModels]);

	const handlePinToggle = async ({ model }: { model: RushcutModel }) => {
		setPinBusyId(model.id);
		try {
			const updated = await pinModel({
				modelId: model.id,
				pinned: !model.pinned,
			});
			setFetchedModels((current) =>
				current.map((m) => (m.id === updated.id ? updated : m)),
			);
			// Keep the live list honest too if the backend doesn't rebroadcast.
			const { models: current, setModels } = useRushcutStore.getState();
			if (current.length > 0) {
				setModels(current.map((m) => (m.id === updated.id ? updated : m)));
			}
		} catch {
			setOffline(true);
		} finally {
			setPinBusyId(null);
		}
	};

	return (
		<div
			className="panel bg-background flex h-full flex-col overflow-hidden rounded-sm border"
			data-testid="models-panel"
		>
			<div className="border-b p-3">
				<div className="flex items-center justify-between">
					<h3 className="text-sm font-medium">Models</h3>
					<span
						className={cn(
							"text-[0.65rem]",
							connected ? "text-emerald-500" : "text-muted-foreground",
						)}
					>
						{connected ? "live" : "polling"}
					</span>
				</div>
				<MemoryBar budget={budget} />
			</div>

			<ScrollArea className="min-h-0 flex-1">
				<div className="flex flex-col gap-1 p-2">
					{offline && models.length === 0 && (
						<p className="text-muted-foreground p-2 text-xs">
							Backend unreachable — is it running on :8000?
						</p>
					)}
					{models.map((model) => (
						<ModelRow
							key={model.id}
							model={model}
							pinBusy={pinBusyId === model.id}
							onPinToggle={handlePinToggle}
						/>
					))}
				</div>
			</ScrollArea>
		</div>
	);
}

function MemoryBar({ budget }: { budget: ModelBudget | null }) {
	const used = budget?.usedGb ?? 0;
	const total = budget?.totalGb ?? 0;
	const percent = total > 0 ? Math.min((used / total) * 100, 100) : 0;

	return (
		<div className="mt-2">
			<div className="text-muted-foreground flex justify-between text-[0.65rem]">
				<span>Unified memory</span>
				<span>
					{budget ? `${used.toFixed(1)} / ${total} GB` : "— / — GB"}
				</span>
			</div>
			<div className="bg-muted mt-1 h-1.5 w-full overflow-hidden rounded-full">
				<div
					className="bg-primary h-full rounded-full transition-[width] duration-500"
					style={{ width: `${percent}%` }}
				/>
			</div>
		</div>
	);
}

function ModelRow({
	model,
	pinBusy,
	onPinToggle,
}: {
	model: RushcutModel;
	pinBusy: boolean;
	onPinToggle: (args: { model: RushcutModel }) => void;
}) {
	return (
		<div className="hover:bg-accent/50 flex items-center gap-2 rounded-sm p-2">
			<span
				className={cn(
					"size-1.5 shrink-0 rounded-full",
					STATE_DOT[model.state] ?? "bg-muted-foreground/40",
				)}
				title={model.state}
			/>
			<div className="min-w-0 flex-1">
				<div className="flex items-center gap-1.5">
					<span className="truncate font-mono text-xs" title={model.bestFor}>
						{model.id}
					</span>
					<Badge
						variant={model.tier === "hero" ? "default" : "secondary"}
						className="shrink-0 px-1.5 py-0 text-[0.6rem] font-medium"
					>
						{model.tier}
					</Badge>
				</div>
				<div className="text-muted-foreground text-[0.65rem]">
					{model.state}
					{model.state === "loading" && "…"} · {model.approxGb.toFixed(1)} GB ·{" "}
					{model.task}
				</div>
			</div>
			<Button
				variant={model.pinned ? "secondary" : "ghost"}
				size="sm"
				disabled={pinBusy}
				onClick={() => onPinToggle({ model })}
				className={cn(
					"h-6 shrink-0 px-2 text-[0.65rem]",
					!model.pinned && "text-muted-foreground",
				)}
				aria-label={model.pinned ? `Unpin ${model.id}` : `Pin ${model.id}`}
			>
				{model.pinned ? "Pinned" : "Pin"}
			</Button>
		</div>
	);
}
