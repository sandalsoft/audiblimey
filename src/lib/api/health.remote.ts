// SvelteKit remote function — server-side query bridging to FastAPI /health
import { query, getRequestEvent } from '$app/server';
import * as v from 'valibot';

const HealthSchema = v.object({
	status: v.string(),
	service: v.string()
});

export type HealthResponse = v.InferOutput<typeof HealthSchema>;

/**
 * Query the FastAPI /health endpoint and validate the response shape.
 * Errors propagate to the nearest svelte:boundary.
 */
export const getHealth = query(async () => {
	const { fetch } = getRequestEvent();
	const response = await fetch('/health');

	if (!response.ok) {
		throw new Error(`Health check failed: ${response.status} ${response.statusText}`);
	}

	const data = await response.json();
	return v.parse(HealthSchema, data);
});
