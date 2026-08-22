"use client";

import { useCallback, useEffect, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
	fetchPeople,
	setPersonPolicy,
	type CastPolicy,
	type Person,
} from "@/lib/rushcut/api";
import { cn } from "@/utils/ui";

const POLICIES: { value: CastPolicy; label: string; activeClass: string }[] = [
	{
		value: "approved",
		label: "Approved",
		activeClass:
			"bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-medium",
	},
	{
		value: "unknown",
		label: "Unknown",
		activeClass:
			"bg-amber-500/15 text-amber-600 dark:text-amber-400 font-medium",
	},
	{
		value: "remove",
		label: "Remove",
		activeClass: "bg-red-500/15 text-red-600 dark:text-red-400 font-medium",
	},
];

export function CastPanel() {
	const [people, setPeople] = useState<Person[]>([]);
	const [offline, setOffline] = useState(false);
	const [busyId, setBusyId] = useState<string | null>(null);

	const refresh = useCallback(async () => {
		try {
			setPeople(await fetchPeople());
			setOffline(false);
		} catch {
			setOffline(true);
		}
	}, []);

	useEffect(() => {
		refresh();
	}, [refresh]);

	const handlePolicy = async ({
		person,
		policy,
	}: {
		person: Person;
		policy: CastPolicy;
	}) => {
		if (person.policy === policy) return;
		setBusyId(person._id);
		try {
			const updated = await setPersonPolicy({ personId: person._id, policy });
			setPeople((current) =>
				current.map((p) => (p._id === updated._id ? updated : p)),
			);
			setOffline(false);
		} catch {
			setOffline(true);
		} finally {
			setBusyId(null);
		}
	};

	const unknownCount = people.filter((p) => p.policy === "unknown").length;

	return (
		<div
			className="panel bg-background flex h-full flex-col overflow-hidden rounded-sm border"
			data-testid="cast-panel"
		>
			<div className="border-b p-3">
				<div className="flex items-center justify-between">
					<h3 className="text-sm font-medium">Cast</h3>
					{unknownCount > 0 && (
						<span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[0.65rem] font-medium text-amber-600 dark:text-amber-400">
							{unknownCount} need{unknownCount === 1 ? "s" : ""} review
						</span>
					)}
				</div>
				<p className="text-muted-foreground mt-1 text-[0.65rem]">
					Only approved people may appear in footage or generated output.
				</p>
			</div>

			<ScrollArea className="min-h-0 flex-1">
				<div className="flex flex-col gap-1.5 p-2">
					{offline && people.length === 0 && (
						<p className="text-muted-foreground p-2 text-xs">
							Backend unreachable — is it running on :8000?
						</p>
					)}
					{people.map((person) => (
						<PersonRow
							key={person._id}
							person={person}
							busy={busyId === person._id}
							onPolicy={handlePolicy}
						/>
					))}
				</div>
			</ScrollArea>
		</div>
	);
}

function PersonRow({
	person,
	busy,
	onPolicy,
}: {
	person: Person;
	busy: boolean;
	onPolicy: (args: { person: Person; policy: CastPolicy }) => void;
}) {
	const isUnknown = person.policy === "unknown";
	const displayName = person.name ?? "Unknown";

	return (
		<div
			className={cn(
				"rounded-sm border p-2",
				isUnknown
					? "border-l-2 border-l-amber-500/80 bg-amber-500/5"
					: "border-transparent",
			)}
		>
			<div className="flex items-center gap-2">
				<div
					className={cn(
						"flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-medium",
						isUnknown
							? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
							: "bg-muted text-muted-foreground",
					)}
				>
					{person.name ? person.name.charAt(0).toUpperCase() : "?"}
				</div>
				<div className="min-w-0 flex-1">
					<div className="flex items-baseline gap-1.5">
						<span
							className={cn(
								"truncate text-xs font-medium",
								!person.name && "text-amber-600 italic dark:text-amber-400",
							)}
						>
							{displayName}
						</span>
						<span className="text-muted-foreground shrink-0 text-[0.65rem]">
							{person.role}
						</span>
					</div>
					{isUnknown && (
						<p className="text-[0.65rem] text-amber-600/90 dark:text-amber-400/90">
							Unreviewed — never auto-passed
						</p>
					)}
				</div>
			</div>

			<div className="bg-muted/50 mt-2 flex rounded-md border p-0.5">
				{POLICIES.map(({ value, label, activeClass }) => (
					<button
						key={value}
						type="button"
						disabled={busy}
						onClick={() => onPolicy({ person, policy: value })}
						className={cn(
							"flex-1 rounded-[5px] px-1 py-0.5 text-[0.65rem] transition-colors",
							person.policy === value
								? activeClass
								: "text-muted-foreground hover:text-foreground",
							busy && "opacity-60",
						)}
					>
						{label}
					</button>
				))}
			</div>
		</div>
	);
}
