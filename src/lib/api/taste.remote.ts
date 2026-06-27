// SvelteKit remote function — server-side queries/commands bridging to FastAPI /api/taste
import { query, command, getRequestEvent } from '$app/server';
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
	const { fetch } = getRequestEvent();
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
	const { fetch } = getRequestEvent();
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
	const { fetch } = getRequestEvent();
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

// --- Taste rules: GET / PUT / DELETE /api/taste/rules ---

const TasteRuleSchema = v.object({
	id: v.number(),
	entity_id: v.number(),
	mode: v.string(),
	label: v.nullable(v.string())
});

const TasteRulesSchema = v.object({
	title: v.array(TasteRuleSchema),
	author: v.array(TasteRuleSchema),
	narrator: v.array(TasteRuleSchema),
	category: v.array(TasteRuleSchema),
	series: v.array(TasteRuleSchema)
});

export type TasteRule = v.InferOutput<typeof TasteRuleSchema>;
export type TasteRules = v.InferOutput<typeof TasteRulesSchema>;

/** Fetch active taste rules grouped by scope. */
export const getTasteRules = query(async () => {
	const { fetch } = getRequestEvent();
	const response = await fetch('/api/taste/rules');
	if (!response.ok) {
		throw new Error(`Failed to fetch taste rules: ${response.status} ${response.statusText}`);
	}
	return v.parse(TasteRulesSchema, await response.json());
});

/** Upsert a taste rule (exclude or include). Idempotent. */
export const putTasteRule = command(
	'unchecked',
	async (rule: { scope: string; entity_id: number; mode?: 'exclude' | 'include' }) => {
		const { fetch } = getRequestEvent();
		const response = await fetch('/api/taste/rules', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				scope: rule.scope,
				entity_id: rule.entity_id,
				mode: rule.mode ?? 'exclude'
			})
		});
		if (!response.ok) {
			throw new Error(`Failed to save taste rule: ${response.status} — ${await response.text()}`);
		}
		return v.parse(
			v.object({ id: v.number(), scope: v.string(), entity_id: v.number(), mode: v.string() }),
			await response.json()
		);
	}
);

/** Delete a taste rule by id (clears the override). */
export const deleteTasteRule = command('unchecked', async (ruleId: number) => {
	const { fetch } = getRequestEvent();
	const response = await fetch(`/api/taste/rules/${ruleId}`, { method: 'DELETE' });
	if (!response.ok) {
		throw new Error(`Failed to delete taste rule: ${response.status} — ${await response.text()}`);
	}
	return v.parse(v.object({ deleted: v.number() }), await response.json());
});

// --- GET /api/taste/entities (search entities to build exclusion rules) ---

const EntityResultsSchema = v.object({
	results: v.array(v.object({ id: v.number(), label: v.string() }))
});

export type EntityResults = v.InferOutput<typeof EntityResultsSchema>;

/** Search authors / genres / titles / series by name to add an exclusion. */
export const searchTasteEntities = query(
	'unchecked',
	async (params: { scope: 'author' | 'category' | 'series' | 'title'; q: string; limit?: number }) => {
		const { fetch } = getRequestEvent();
		const limit = params.limit ?? 10;
		const url = `/api/taste/entities?scope=${encodeURIComponent(params.scope)}&q=${encodeURIComponent(params.q)}&limit=${limit}`;
		const response = await fetch(url);
		if (!response.ok) {
			throw new Error(`Failed to search entities: ${response.status} ${response.statusText}`);
		}
		return v.parse(EntityResultsSchema, await response.json());
	}
);
