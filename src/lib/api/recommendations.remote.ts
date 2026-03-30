// SvelteKit remote function — server-side queries/commands bridging to FastAPI /api/recommendations
import { query, command, getRequestEvent } from '$app/server';
import * as v from 'valibot';

// --- Shared sub-schemas ---

const BookSchema = v.object({
	asin: v.string(),
	title: v.string(),
	runtime_minutes: v.nullable(v.number()),
	runtime_hours: v.nullable(v.number())
});

const PricingSchema = v.nullable(
	v.object({
		member_price: v.nullable(v.number()),
		list_price: v.nullable(v.number())
	})
);

const ScoreComponentSchema = v.object({
	source: v.string(),
	raw_value: v.number(),
	weight: v.number(),
	weighted_value: v.number(),
	detail: v.optional(v.string())
});

// --- GET /api/recommendations ---

const RecommendationItemSchema = v.object({
	id: v.number(),
	book: BookSchema,
	score: v.number(),
	old_confidence: v.nullable(v.number()),
	suggestion_type: v.nullable(v.string()),
	source_name: v.nullable(v.string()),
	explanation: v.string(),
	short_explanation: v.string(),
	score_breakdown: v.array(ScoreComponentSchema),
	pricing: PricingSchema
});

const RecommendationsResponseSchema = v.object({
	items: v.array(RecommendationItemSchema),
	total: v.number(),
	offset: v.number(),
	limit: v.number()
});

export type RecommendationItem = v.InferOutput<typeof RecommendationItemSchema>;
export type RecommendationsResponse = v.InferOutput<typeof RecommendationsResponseSchema>;

/**
 * Fetch paginated scored recommendations from the backend.
 * Accepts limit (default 20) and offset (default 0) for pagination.
 */
export const getRecommendations = query('unchecked', async (params: { limit?: number; offset?: number } | undefined) => {
	const { fetch } = getRequestEvent();
	const limit = params?.limit ?? 20;
	const offset = params?.offset ?? 0;
	const url = `/api/recommendations?limit=${limit}&offset=${offset}`;
	const response = await fetch(url);

	if (!response.ok) {
		throw new Error(`Failed to fetch recommendations: ${response.status} ${response.statusText}`);
	}

	const data = await response.json();
	return v.parse(RecommendationsResponseSchema, data);
});

// --- GET /api/recommendations/series ---

const NextBookSchema = v.object({
	asin: v.string(),
	title: v.string(),
	sequence: v.nullable(v.number()),
	runtime_minutes: v.nullable(v.number()),
	pricing: PricingSchema
});

const SeriesItemSchema = v.object({
	series_title: v.string(),
	total_books: v.number(),
	owned_count: v.number(),
	progress_pct: v.number(),
	next_sequence: v.number(),
	avg_rating: v.number(),
	urgency_score: v.number(),
	next_book: v.optional(NextBookSchema)
});

const SeriesResponseSchema = v.object({
	series: v.array(SeriesItemSchema)
});

export type SeriesItem = v.InferOutput<typeof SeriesItemSchema>;
export type SeriesResponse = v.InferOutput<typeof SeriesResponseSchema>;

/**
 * Fetch incomplete series with urgency ranking and next-book info.
 */
export const getSeriesRecommendations = query(async () => {
	const { fetch } = getRequestEvent();
	const response = await fetch('/api/recommendations/series');

	if (!response.ok) {
		throw new Error(
			`Failed to fetch series recommendations: ${response.status} ${response.statusText}`
		);
	}

	const data = await response.json();
	return v.parse(SeriesResponseSchema, data);
});

// --- POST /api/recommendations/{rec_id}/dismiss ---

const DismissResponseSchema = v.object({
	status: v.string(),
	id: v.number()
});

export type DismissResponse = v.InferOutput<typeof DismissResponseSchema>;

/**
 * Dismiss a recommendation so it won't appear again.
 * Uses "unchecked" input validation since the arg is a simple number.
 */
export const dismissRecommendation = command('unchecked', async (recId: number) => {
	const { fetch } = getRequestEvent();
	const response = await fetch(`/api/recommendations/${recId}/dismiss`, {
		method: 'POST'
	});

	if (!response.ok) {
		throw new Error(`Failed to dismiss recommendation ${recId}: ${response.status} ${response.statusText}`);
	}

	const data = await response.json();
	return v.parse(DismissResponseSchema, data);
});
