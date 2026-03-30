// SvelteKit remote function — server-side query bridging to FastAPI /api/search
import { query, getRequestEvent } from '$app/server';
import * as v from 'valibot';

/** A search result item from the API. */
const SearchResultSchema = v.object({
	asin: v.string(),
	title: v.string(),
	authors: v.string(),
	runtime_hours: v.nullable(v.number()),
	similarity_score: v.nullable(v.number()),
	user_rating: v.nullable(v.number()),
	categories: v.string()
});

/** Full search response envelope. */
const SearchResponseSchema = v.object({
	items: v.array(SearchResultSchema),
	query: v.string()
});

export type SearchResult = v.InferOutput<typeof SearchResultSchema>;
export type SearchResponse = v.InferOutput<typeof SearchResponseSchema>;

/** Search params accepted by the remote function. */
export interface SearchParams {
	q: string;
	min_runtime?: number;
	max_runtime?: number;
	min_rating?: number;
	limit?: number;
}

/**
 * Search books by natural language query with optional runtime/rating filters.
 * Wraps GET /api/search on the FastAPI backend.
 */
export const searchBooks = query(
	'unchecked',
	async (params: SearchParams) => {
		const { fetch } = getRequestEvent();
		const qs = new URLSearchParams({ q: params.q });
		if (params.min_runtime != null) qs.set('min_runtime', String(params.min_runtime));
		if (params.max_runtime != null) qs.set('max_runtime', String(params.max_runtime));
		if (params.min_rating != null) qs.set('min_rating', String(params.min_rating));
		if (params.limit != null) qs.set('limit', String(params.limit));

		const response = await fetch(`/api/search?${qs}`);
		if (!response.ok) {
			const body = await response.text().catch(() => '');
			throw new Error(`Search failed: ${response.status} ${response.statusText}${body ? ` — ${body}` : ''}`);
		}
		return v.parse(SearchResponseSchema, await response.json());
	}
);
