/**
 * Typed fetch helpers for the RushCut backend (docs/api.md).
 *
 * Client-safe: reads NEXT_PUBLIC_BACKEND_URL directly so Next.js can inline
 * it in the browser bundle (importing src/env/web.ts would drag server-only
 * vars into the client). The backend replies with `{ "error": {...} }` JSON
 * bodies instead of bare 404s — `request` folds both shapes into one error.
 */

export function getBackendUrl(): string {
	return (
		process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000"
	).replace(/\/$/, "");
}

export function getBackendWsUrl(): string {
	return `${getBackendUrl().replace(/^http/, "ws")}/ws`;
}

// ------------------------------------------------------------------ jobs

export type JobState =
	| "queued"
	| "running"
	| "complete"
	| "failed"
	| "cancelled"
	| "policy_blocked";

export interface PolicyTrack {
	trackId: string;
	personId?: string | null;
	confidence?: number;
	frames?: number[];
	cropUrl?: string;
	reason?: string;
}

export interface JobPolicy {
	verdict: "clear" | "blocked" | "needs_review";
	unapproved?: PolicyTrack[];
	unresolved?: PolicyTrack[];
	remediation?: "inpaint" | "regenerate" | "rejected" | null;
	remediatedAssetId?: string | null;
}

export interface RushcutJob {
	jobId: string;
	projectId: string;
	type: string;
	state: JobState;
	progress: number | null;
	stage: string | null;
	message: string | null;
	createdAt: string;
	startedAt: string | null;
	finishedAt: string | null;
	result: Record<string, unknown> | null;
	error: { code: string; message: string } | null;
	policy: JobPolicy | null;
}

// ---------------------------------------------------------------- models

export type ModelState = "idle" | "loading" | "resident" | "evicting";

export interface RushcutModel {
	id: string;
	task: string;
	tier: "draft" | "hero";
	precision: string;
	approxGb: number;
	loadSeconds: number;
	license: string;
	bestFor: string;
	state: ModelState;
	pinned: boolean;
}

export interface ModelBudget {
	budgetGb: Record<string, number>;
	totalGb: number;
	usedGb: number;
}

// ---------------------------------------------------------------- people

export type CastPolicy = "approved" | "unknown" | "remove";

export interface PersonConsent {
	recordUrl: string;
	scope: string;
	noticeAt: string;
	signedAt: string;
	revokedAt: string | null;
}

export interface Person {
	_id: string;
	projectId: string;
	name: string | null;
	role: "principal" | "background" | "bystander" | string;
	policy: CastPolicy;
	refs?: {
		face?: string | null;
		body?: string | null;
		wardrobe?: string | null;
	} | null;
	consent?: PersonConsent | null;
}

// ----------------------------------------------------------------- agent

export interface AgentToolCall {
	name: string;
	arguments: Record<string, unknown>;
	tier?: string;
	result?: unknown;
}

export interface AgentPendingPlan {
	toolCalls: { name: string; arguments: Record<string, unknown> }[];
}

export interface AgentChatResponse {
	reply: string;
	toolCalls: AgentToolCall[];
	pendingPlan: AgentPendingPlan | null;
}

export interface AgentTool {
	name: string;
	tier: "direct" | "propose" | "plan";
	description: string;
	parameters: Record<string, unknown>;
}

// ------------------------------------------------------------- ws frames

export type RushcutFrame =
	| { kind: "job"; job: RushcutJob }
	| { kind: "log"; jobId: string; line: string }
	| { kind: "models"; models: RushcutModel[] };

// --------------------------------------------------------------- fetcher

export class RushcutApiError extends Error {
	status?: number;
	code?: string;

	constructor({
		message,
		status,
		code,
	}: {
		message: string;
		status?: number;
		code?: string;
	}) {
		super(message);
		this.name = "RushcutApiError";
		this.status = status;
		this.code = code;
	}
}

async function request<T>({
	path,
	method = "GET",
	body,
}: {
	path: string;
	method?: "GET" | "POST";
	body?: unknown;
}): Promise<T> {
	const res = await fetch(`${getBackendUrl()}${path}`, {
		method,
		headers:
			body !== undefined ? { "Content-Type": "application/json" } : undefined,
		body: body !== undefined ? JSON.stringify(body) : undefined,
	});
	const text = await res.text();
	let data: unknown = null;
	try {
		data = text ? JSON.parse(text) : null;
	} catch {
		// non-JSON body (proxy error page etc.) — fall through to status check
	}
	if (!res.ok) {
		const detail = (data as { detail?: string } | null)?.detail;
		throw new RushcutApiError({
			message: detail ?? `${method} ${path} failed (${res.status})`,
			status: res.status,
		});
	}
	const error = (data as { error?: { code?: string; message?: string } } | null)
		?.error;
	if (error) {
		throw new RushcutApiError({
			message: error.message ?? "backend error",
			status: res.status,
			code: error.code,
		});
	}
	return data as T;
}

// ------------------------------------------------------------- endpoints

export function fetchModels(): Promise<RushcutModel[]> {
	return request({ path: "/models" });
}

export function fetchModelBudget(): Promise<ModelBudget> {
	return request({ path: "/models/budget" });
}

export function pinModel({
	modelId,
	pinned,
}: {
	modelId: string;
	pinned: boolean;
}): Promise<RushcutModel> {
	return request({
		path: `/models/${encodeURIComponent(modelId)}/pin`,
		method: "POST",
		body: { pinned },
	});
}

export function fetchPeople(): Promise<Person[]> {
	return request({ path: "/people" });
}

export function setPersonPolicy({
	personId,
	policy,
	name,
}: {
	personId: string;
	policy: CastPolicy;
	name?: string;
}): Promise<Person> {
	return request({
		path: `/people/${encodeURIComponent(personId)}/policy`,
		method: "POST",
		body: name !== undefined ? { policy, name } : { policy },
	});
}

export function createJob({
	type,
	projectId,
	params,
}: {
	type: string;
	projectId?: string;
	params?: Record<string, unknown>;
}): Promise<RushcutJob> {
	return request({
		path: "/jobs",
		method: "POST",
		body: { type, ...(projectId ? { projectId } : {}), params: params ?? {} },
	});
}

export function fetchJob({ jobId }: { jobId: string }): Promise<RushcutJob> {
	return request({ path: `/jobs/${encodeURIComponent(jobId)}` });
}

export function sendAgentChat({
	message,
	approvePlan = false,
}: {
	message: string;
	approvePlan?: boolean;
}): Promise<AgentChatResponse> {
	return request({
		path: "/agent/chat",
		method: "POST",
		body: { message, approvePlan },
	});
}

export function fetchAgentTools(): Promise<AgentTool[]> {
	return request({ path: "/agent/tools" });
}
