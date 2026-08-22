import { z } from "zod";

const webEnvSchema = z.object({
	// Node
	NODE_ENV: z.enum(["development", "production", "test"]),
	ANALYZE: z.string().optional(),
	NEXT_RUNTIME: z.enum(["nodejs", "edge"]).optional(),

	// Public
	NEXT_PUBLIC_SITE_URL: z.url().default("http://localhost:3000"),
	NEXT_PUBLIC_MARBLE_API_URL: z.url(),
	NEXT_PUBLIC_BACKEND_URL: z.url().default("http://localhost:8000"),

	// Server
	DATABASE_URL: z.string().refine(
		(url) =>
			url.startsWith("postgres://") || url.startsWith("postgresql://"),
		"DATABASE_URL must be a postgres:// or postgresql:// URL",
	),

	BETTER_AUTH_SECRET: z.string(),
	UPSTASH_REDIS_REST_URL: z.url(),
	UPSTASH_REDIS_REST_TOKEN: z.string(),
	MARBLE_WORKSPACE_KEY: z.string(),
	FREESOUND_CLIENT_ID: z.string(),
	FREESOUND_API_KEY: z.string(),
});

export type WebEnv = z.infer<typeof webEnvSchema>;

export const webEnv = webEnvSchema.parse(process.env);

/** ws(s):// form of NEXT_PUBLIC_BACKEND_URL ending in /ws — the frame
 * stream from docs/api.md §1. Server-side only; client code derives the
 * same value in src/lib/rushcut/api.ts so NEXT_PUBLIC_ inlining works. */
export const backendWsUrl = `${webEnv.NEXT_PUBLIC_BACKEND_URL.replace(
	/^http/,
	"ws",
)}/ws`;
