"use client";

import { useEffect, useRef, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
	fetchAgentTools,
	sendAgentChat,
	type AgentPendingPlan,
	type AgentTool,
	type AgentToolCall,
} from "@/lib/rushcut/api";
import { cn } from "@/utils/ui";

interface ChatMessage {
	id: string;
	role: "user" | "assistant";
	text: string;
	toolCalls?: AgentToolCall[];
}

const EXAMPLE_PROMPTS = [
	"What models are loaded right now?",
	"Who is in the cast, and does anyone need review?",
	"Generate a draft shot of Dana crossing the lobby",
];

let messageCounter = 0;
function nextMessageId(): string {
	messageCounter += 1;
	return `msg_${messageCounter}`;
}

export function AIChatPanel() {
	const [messages, setMessages] = useState<ChatMessage[]>([]);
	const [input, setInput] = useState("");
	const [pendingPlan, setPendingPlan] = useState<AgentPendingPlan | null>(null);
	const [sending, setSending] = useState(false);
	const [brainOffline, setBrainOffline] = useState(false);
	const [toolTiers, setToolTiers] = useState<Record<string, AgentTool>>({});
	const scrollAnchorRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		fetchAgentTools()
			.then((tools) =>
				setToolTiers(
					Object.fromEntries(tools.map((tool) => [tool.name, tool])),
				),
			)
			.catch(() => {
				// tools listing is decoration; chat errors are surfaced separately
			});
	}, []);

	useEffect(() => {
		scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth" });
	}, [messages, pendingPlan, sending]);

	const runTurn = async ({
		message,
		approvePlan = false,
	}: {
		message: string;
		approvePlan?: boolean;
	}) => {
		setSending(true);
		try {
			const response = await sendAgentChat({ message, approvePlan });
			setBrainOffline(false);
			setMessages((current) => [
				...current,
				{
					id: nextMessageId(),
					role: "assistant",
					text: response.reply,
					toolCalls: response.toolCalls,
				},
			]);
			setPendingPlan(response.pendingPlan);
		} catch {
			setBrainOffline(true);
		} finally {
			setSending(false);
		}
	};

	const handleSend = () => {
		const message = input.trim();
		if (!message || sending) return;
		setInput("");
		setMessages((current) => [
			...current,
			{ id: nextMessageId(), role: "user", text: message },
		]);
		runTurn({ message });
	};

	const handleApprovePlan = () => {
		if (sending) return;
		setPendingPlan(null);
		runTurn({ message: "", approvePlan: true });
	};

	const handleDiscardPlan = () => {
		setPendingPlan(null);
		setMessages((current) => [
			...current,
			{
				id: nextMessageId(),
				role: "user",
				text: "(plan discarded — nothing was run)",
			},
		]);
	};

	return (
		<div
			className="panel bg-background flex h-full flex-col overflow-hidden rounded-sm border"
			data-testid="ai-chat-panel"
		>
			<div className="border-b p-3">
				<h3 className="text-sm font-medium">AI</h3>
				<p className="text-muted-foreground mt-0.5 text-[0.65rem]">
					On-box agent — plan-tier work runs only after you approve.
				</p>
			</div>

			<ScrollArea className="min-h-0 flex-1">
				<div className="flex flex-col gap-2 p-3">
					{messages.length === 0 && !brainOffline && (
						<EmptyState
							onPrompt={(prompt) => setInput(prompt)}
							disabled={sending}
						/>
					)}
					{messages.map((message) => (
						<MessageBubble
							key={message.id}
							message={message}
							toolTiers={toolTiers}
						/>
					))}
					{pendingPlan && (
						<PlanCard
							plan={pendingPlan}
							toolTiers={toolTiers}
							disabled={sending}
							onApprove={handleApprovePlan}
							onDiscard={handleDiscardPlan}
						/>
					)}
					{sending && (
						<p className="text-muted-foreground animate-pulse text-xs">
							thinking…
						</p>
					)}
					{brainOffline && (
						<div className="rounded-sm border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-600 dark:text-amber-400">
							Brain offline (runs on the GB10). The agent LLM isn&apos;t
							reachable from here — everything else in the editor still works.
						</div>
					)}
					<div ref={scrollAnchorRef} />
				</div>
			</ScrollArea>

			<div className="border-t p-2">
				<div className="flex items-end gap-1.5">
					<Textarea
						value={input}
						onChange={(event) => setInput(event.target.value)}
						onKeyDown={(event) => {
							if (event.key === "Enter" && !event.shiftKey) {
								event.preventDefault();
								handleSend();
							}
						}}
						placeholder="Ask the agent…"
						rows={2}
						className="min-h-0 flex-1 resize-none text-xs"
					/>
					<Button
						size="sm"
						onClick={handleSend}
						disabled={sending || input.trim().length === 0}
						className="shrink-0"
					>
						Send
					</Button>
				</div>
			</div>
		</div>
	);
}

function EmptyState({
	onPrompt,
	disabled,
}: {
	onPrompt: (prompt: string) => void;
	disabled: boolean;
}) {
	return (
		<div className="text-muted-foreground py-4 text-xs">
			<p>
				The agent can inspect the cast and model registry, stage timeline
				edits for your review, and plan generation jobs that run only after
				you approve them. Try:
			</p>
			<div className="mt-2 flex flex-col gap-1">
				{EXAMPLE_PROMPTS.map((prompt) => (
					<button
						key={prompt}
						type="button"
						disabled={disabled}
						onClick={() => onPrompt(prompt)}
						className="hover:bg-accent hover:text-foreground rounded-sm border px-2 py-1 text-left transition-colors"
					>
						{prompt}
					</button>
				))}
			</div>
		</div>
	);
}

function MessageBubble({
	message,
	toolTiers,
}: {
	message: ChatMessage;
	toolTiers: Record<string, AgentTool>;
}) {
	return (
		<div
			className={cn(
				"max-w-[92%] rounded-md px-2.5 py-1.5 text-xs",
				message.role === "user"
					? "bg-primary text-primary-foreground self-end"
					: "bg-muted/60 self-start",
			)}
		>
			<p className="whitespace-pre-wrap">{message.text}</p>
			{message.toolCalls && message.toolCalls.length > 0 && (
				<div className="mt-1.5 flex flex-wrap gap-1">
					{message.toolCalls.map((call, index) => (
						<ToolCallChip
							key={`${message.id}_${index}`}
							call={call}
							tier={call.tier ?? toolTiers[call.name]?.tier}
						/>
					))}
				</div>
			)}
		</div>
	);
}

function ToolCallChip({
	call,
	tier,
}: {
	call: AgentToolCall;
	tier?: string;
}) {
	const [expanded, setExpanded] = useState(false);
	return (
		<button
			type="button"
			onClick={() => setExpanded((current) => !current)}
			className="bg-background/80 hover:bg-accent max-w-full rounded-sm border px-1.5 py-0.5 text-left font-mono text-[0.6rem] transition-colors"
		>
			<span className="text-foreground/90">{call.name}</span>
			{tier && <span className="text-muted-foreground"> · {tier}</span>}
			{expanded && (
				<pre className="text-muted-foreground mt-1 overflow-x-auto whitespace-pre-wrap break-all">
					{JSON.stringify(
						{ arguments: call.arguments, result: call.result },
						null,
						1,
					)}
				</pre>
			)}
		</button>
	);
}

function summarizeArguments(args: Record<string, unknown>): string {
	const entries = Object.entries(args);
	if (entries.length === 0) return "no parameters";
	return entries
		.map(([key, value]) => {
			const rendered =
				typeof value === "string" ? value : JSON.stringify(value);
			return `${key}: ${rendered.length > 48 ? `${rendered.slice(0, 48)}…` : rendered}`;
		})
		.join(" · ");
}

function PlanCard({
	plan,
	toolTiers,
	disabled,
	onApprove,
	onDiscard,
}: {
	plan: AgentPendingPlan;
	toolTiers: Record<string, AgentTool>;
	disabled: boolean;
	onApprove: () => void;
	onDiscard: () => void;
}) {
	return (
		<div className="border-primary/40 bg-primary/5 rounded-md border p-2.5">
			<p className="text-xs font-medium">Plan — needs your approval</p>
			<div className="mt-1.5 flex flex-col gap-1.5">
				{plan.toolCalls.map((call, index) => (
					<div key={`${call.name}_${index}`} className="text-[0.65rem]">
						<span className="font-mono font-medium">{call.name}</span>
						{toolTiers[call.name]?.description && (
							<span className="text-muted-foreground">
								{" "}
								— {toolTiers[call.name]?.description}
							</span>
						)}
						<p className="text-muted-foreground mt-0.5 break-words">
							{summarizeArguments(call.arguments)}
						</p>
					</div>
				))}
			</div>
			<p className="text-muted-foreground mt-1.5 text-[0.6rem]">
				Estimated cost: runs on this box; generation jobs typically take
				1–10 min and results land in the bin as candidates, never in the cut.
			</p>
			<div className="mt-2 flex gap-1.5">
				<Button
					size="sm"
					disabled={disabled}
					onClick={onApprove}
					className="h-6 px-2 text-[0.65rem]"
				>
					Approve &amp; run
				</Button>
				<Button
					size="sm"
					variant="outline"
					disabled={disabled}
					onClick={onDiscard}
					className="h-6 px-2 text-[0.65rem]"
				>
					Discard
				</Button>
			</div>
		</div>
	);
}
