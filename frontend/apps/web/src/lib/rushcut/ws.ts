"use client";

/**
 * One WebSocket to the RushCut backend, fanned out through a zustand store.
 *
 * Frames are whole objects (docs/api.md §1): `job` frames replace the job by
 * id, `models` frames replace the whole list — no delta reconciliation. The
 * socket is a module singleton ref-counted by `useRushcutSocket`, so the
 * three panels and any timeline elements share a single connection.
 */

import { useEffect } from "react";
import { create } from "zustand";
import {
	getBackendWsUrl,
	type RushcutFrame,
	type RushcutJob,
	type RushcutModel,
} from "./api";

interface RushcutState {
	connected: boolean;
	/** Latest whole Job object per jobId, straight off the socket. */
	jobs: Record<string, RushcutJob>;
	/** Latest whole models list; empty until the first frame or fetch. */
	models: RushcutModel[];
	/** Most recent log line per jobId (kind: "log" frames). */
	lastLogByJobId: Record<string, string>;
	setConnected: (connected: boolean) => void;
	applyFrame: (frame: RushcutFrame) => void;
	setModels: (models: RushcutModel[]) => void;
}

export const useRushcutStore = create<RushcutState>()((set) => ({
	connected: false,
	jobs: {},
	models: [],
	lastLogByJobId: {},
	setConnected: (connected) => set({ connected }),
	setModels: (models) => set({ models }),
	applyFrame: (frame) =>
		set((state) => {
			switch (frame.kind) {
				case "job":
					return {
						jobs: { ...state.jobs, [frame.job.jobId]: frame.job },
					};
				case "models":
					return { models: frame.models };
				case "log":
					return {
						lastLogByJobId: {
							...state.lastLogByJobId,
							[frame.jobId]: frame.line,
						},
					};
				default:
					return state;
			}
		}),
}));

const RECONNECT_DELAY_MS = 2000;

let socket: WebSocket | null = null;
let refCount = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function connect() {
	if (socket || typeof WebSocket === "undefined") return;
	let ws: WebSocket;
	try {
		ws = new WebSocket(getBackendWsUrl());
	} catch {
		scheduleReconnect();
		return;
	}
	socket = ws;
	ws.onopen = () => {
		useRushcutStore.getState().setConnected(true);
	};
	ws.onmessage = (event) => {
		try {
			const frame = JSON.parse(event.data as string) as RushcutFrame;
			if (frame && typeof frame === "object" && "kind" in frame) {
				useRushcutStore.getState().applyFrame(frame);
			}
		} catch {
			// malformed frame — ignore, the next whole-object frame supersedes it
		}
	};
	ws.onclose = () => {
		if (socket === ws) socket = null;
		useRushcutStore.getState().setConnected(false);
		scheduleReconnect();
	};
	ws.onerror = () => {
		ws.close();
	};
}

function scheduleReconnect() {
	if (refCount <= 0 || reconnectTimer) return;
	reconnectTimer = setTimeout(() => {
		reconnectTimer = null;
		if (refCount > 0) connect();
	}, RECONNECT_DELAY_MS);
}

/**
 * Keep the shared socket alive while mounted and subscribe to the store.
 * Panels use this; leaf components that only read one job should use
 * `useRushcutJob` to avoid re-rendering on every frame.
 */
export function useRushcutSocket(): RushcutState {
	useEffect(() => {
		refCount += 1;
		connect();
		return () => {
			refCount -= 1;
			if (refCount === 0) {
				if (reconnectTimer) {
					clearTimeout(reconnectTimer);
					reconnectTimer = null;
				}
				socket?.close();
				socket = null;
			}
		};
	}, []);
	return useRushcutStore();
}

/** Latest streamed Job for a jobId, or undefined before its first frame. */
export function useRushcutJob(jobId: string | undefined): RushcutJob | undefined {
	return useRushcutStore((state) =>
		jobId ? state.jobs[jobId] : undefined,
	);
}
