// SvelteKit remote function — server-side queries/commands bridging to FastAPI /api/taste
import { query, command } from '$app/server';
import * as v from 'valibot';

// --- Schemas ---

const TasteProfileSchema = v.object({
	profile_text: v.nullable(v.string()),
	profile_edited: v.nullable(v.string()),
	books_included: v.number(),
	generated_at: v.nullable(v.string()),
	has_vector: v.boolean()
});

const GenerateResponseSchema = v.object({
	profile_text: v.string(),
	books_included: v.number(),
	generated_at: v.string()
});

const UpdateResponseSchema = v.object({
	profile_edited: v.string(),
	updated_at: v.nullable(v.string())
});

export type TasteProfile = v.InferOutput<typeof TasteProfileSchema>;
export type GenerateResponse = v.InferOutput<typeof GenerateResponseSchema>;
export type UpdateResponse = v.InferOutput<typeof UpdateResponseSchema>;

// --- GET /api/taste/profile ---

/**
 * Fetch the user's taste profile — text, edit, book count, generation date, and vector status.
 */
export const getTasteProfile = query(async () => {
	const response = await fetch('/api/taste/profile');
	if (!response.ok) {
		throw new Error(`Failed to fetch taste profile: ${response.status} ${response.statusText}`);
	}
	return v.parse(TasteProfileSchema, await response.json());
});

// --- POST /api/taste/generate ---

/**
 * Generate (or regenerate) the taste profile. Returns the new profile text.
 */
export const generateTasteProfile = command(async () => {
	const response = await fetch('/api/taste/generate', { method: 'POST' });
	if (!response.ok) {
		const body = await response.text();
		throw new Error(`Failed to generate taste profile: ${response.status} — ${body}`);
	}
	return v.parse(GenerateResponseSchema, await response.json());
});

// --- PUT /api/taste/profile ---

/**
 * Save user edits to their taste profile.
 */
export const updateTasteProfile = command('unchecked', async (profileEdited: string) => {
	const response = await fetch('/api/taste/profile', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ profile_edited: profileEdited })
	});
	if (!response.ok) {
		const body = await response.text();
		throw new Error(`Failed to update taste profile: ${response.status} — ${body}`);
	}
	return v.parse(UpdateResponseSchema, await response.json());
});
