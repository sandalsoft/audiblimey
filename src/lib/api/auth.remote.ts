// SvelteKit remote function — server-side queries/commands bridging to FastAPI /api/auth
import { query, command, getRequestEvent } from '$app/server';
import * as v from 'valibot';

// --- GET /api/auth/audible/status ---

const AuthStatusSchema = v.object({
	linked: v.boolean(),
	marketplace: v.optional(v.string()),
	linked_at: v.optional(v.nullable(v.string()))
});

export type AuthStatus = v.InferOutput<typeof AuthStatusSchema>;

export const getAudibleAuthStatus = query(async () => {
	const { fetch } = getRequestEvent();
	const response = await fetch('/api/auth/audible/status');
	if (!response.ok) {
		throw new Error(`Failed to check auth status: ${response.status}`);
	}
	return v.parse(AuthStatusSchema, await response.json());
});

// --- POST /api/auth/audible/start ---

const StartAuthSchema = v.object({
	oauth_url: v.string(),
	session_id: v.string()
});

export type StartAuthResponse = v.InferOutput<typeof StartAuthSchema>;

export const startAudibleAuth = command(async () => {
	const { fetch } = getRequestEvent();
	const response = await fetch('/api/auth/audible/start', { method: 'POST' });
	if (!response.ok) {
		const body = await response.text();
		throw new Error(`Failed to start auth: ${response.status} — ${body}`);
	}
	return v.parse(StartAuthSchema, await response.json());
});

// --- POST /api/auth/audible/complete ---

const CompleteAuthSchema = v.object({
	status: v.string(),
	marketplace: v.string()
});

export type CompleteAuthResponse = v.InferOutput<typeof CompleteAuthSchema>;

export const completeAudibleAuth = command(
	'unchecked',
	async (params: { session_id: string; response_url: string }) => {
		const { fetch } = getRequestEvent();
		const response = await fetch('/api/auth/audible/complete', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(params)
		});
		if (!response.ok) {
			const body = await response.text();
			throw new Error(`Auth failed: ${response.status} — ${body}`);
		}
		return v.parse(CompleteAuthSchema, await response.json());
	}
);
