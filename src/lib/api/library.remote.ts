// SvelteKit remote function — server-side queries bridging to FastAPI /api/library, /api/books, /api/authors, /api/narrators
import { query, command, getRequestEvent } from '$app/server';
import * as v from 'valibot';

// --- Shared sub-schemas ---

/** A taste rule reference attached to a title or entity (null when no rule). */
const RuleRefSchema = v.nullable(v.object({ id: v.number(), mode: v.string() }));

/** An author/narrator/category/series on a book, with its taste rule (if any). */
const EntityRefSchema = v.object({
	id: v.number(),
	name: v.string(),
	rule: RuleRefSchema
});

export type RuleRef = v.InferOutput<typeof RuleRefSchema>;
export type EntityRef = v.InferOutput<typeof EntityRefSchema>;

/** A book in the user's library (list view). */
const LibraryItemSchema = v.object({
	book_id: v.number(),
	asin: v.string(),
	title: v.string(),
	image_url: v.nullable(v.string()),
	runtime_minutes: v.nullable(v.number()),
	runtime_hours: v.nullable(v.number()),
	percent_complete: v.number(),
	is_finished: v.nullable(v.boolean()),
	purchase_date: v.nullable(v.string()),
	user_rating: v.nullable(v.number()),
	user_manual_rating: v.nullable(v.number()),
	taste_excluded: v.boolean(),
	authors: v.string(),
	narrators: v.string(),
	authors_ref: v.array(EntityRefSchema),
	narrators_ref: v.array(EntityRefSchema),
	categories: v.array(EntityRefSchema),
	series: v.array(EntityRefSchema),
	title_rule: RuleRefSchema
});

/** Paginated library response. */
const LibraryResponseSchema = v.object({
	items: v.array(LibraryItemSchema),
	total: v.number(),
	offset: v.number(),
	limit: v.number()
});

export type LibraryItem = v.InferOutput<typeof LibraryItemSchema>;
export type LibraryResponse = v.InferOutput<typeof LibraryResponseSchema>;

// --- GET /api/library ---

/**
 * Fetch the user's paginated library with optional search and status filter.
 */
export const getLibrary = query(
	'unchecked',
	async (
		params:
			| { limit?: number; offset?: number; search?: string; status?: string; taste?: string }
			| undefined
	) => {
		const { fetch } = getRequestEvent();
		const limit = params?.limit ?? 20;
		const offset = params?.offset ?? 0;
		const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
		if (params?.search) qs.set('search', params.search);
		if (params?.status) qs.set('status', params.status);
		if (params?.taste) qs.set('taste', params.taste);

		const response = await fetch(`/api/library?${qs}`);
		if (!response.ok) {
			throw new Error(`Failed to fetch library: ${response.status} ${response.statusText}`);
		}
		return v.parse(LibraryResponseSchema, await response.json());
	}
);

// --- PUT /api/library/{asin}/rating ---

const RatingResponseSchema = v.object({
	asin: v.string(),
	user_manual_rating: v.nullable(v.number())
});

/**
 * Set (1–5) or clear (null) the personal rating for a library title.
 */
export const setRating = command(
	'unchecked',
	async (args: { asin: string; rating: number | null }) => {
		const { fetch } = getRequestEvent();
		const response = await fetch(`/api/library/${encodeURIComponent(args.asin)}/rating`, {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ rating: args.rating })
		});
		if (!response.ok) {
			throw new Error(`Failed to set rating: ${response.status} — ${await response.text()}`);
		}
		return v.parse(RatingResponseSchema, await response.json());
	}
);

// --- GET /api/books/{asin} ---

const PersonRefSchema = v.object({
	id: v.number(),
	asin: v.nullable(v.string()),
	name: v.string(),
	rule: RuleRefSchema
});

const SeriesRefSchema = v.object({
	id: v.number(),
	asin: v.nullable(v.string()),
	title: v.string(),
	sequence: v.nullable(v.number()),
	rule: RuleRefSchema
});

const CategoryRefSchema = v.object({
	id: v.number(),
	name: v.string(),
	rule: RuleRefSchema
});

const BookPricingSchema = v.nullable(
	v.object({
		member_price: v.nullable(v.number()),
		list_price: v.nullable(v.number()),
		credit_price: v.nullable(v.number()),
		currency: v.nullable(v.string()),
		price_date: v.nullable(v.string())
	})
);

const UserLibraryEntrySchema = v.nullable(
	v.object({
		percent_complete: v.number(),
		is_finished: v.nullable(v.boolean()),
		purchase_date: v.nullable(v.string()),
		user_rating: v.nullable(v.number())
	})
);

const BookDetailSchema = v.object({
	book_id: v.number(),
	asin: v.string(),
	title: v.string(),
	image_url: v.nullable(v.string()),
	subtitle: v.nullable(v.string()),
	runtime_minutes: v.nullable(v.number()),
	runtime_hours: v.nullable(v.number()),
	summary: v.nullable(v.string()),
	language: v.nullable(v.string()),
	publisher: v.nullable(v.string()),
	release_date: v.nullable(v.string()),
	content_type: v.nullable(v.string()),
	authors: v.array(PersonRefSchema),
	narrators: v.array(PersonRefSchema),
	series: v.array(SeriesRefSchema),
	categories: v.array(CategoryRefSchema),
	title_rule: RuleRefSchema,
	taste_excluded: v.boolean(),
	pricing: BookPricingSchema,
	user_library: UserLibraryEntrySchema
});

export type PersonRef = v.InferOutput<typeof PersonRefSchema>;
export type SeriesRef = v.InferOutput<typeof SeriesRefSchema>;
export type BookPricing = v.InferOutput<typeof BookPricingSchema>;
export type UserLibraryEntry = v.InferOutput<typeof UserLibraryEntrySchema>;
export type BookDetail = v.InferOutput<typeof BookDetailSchema>;

/**
 * Fetch full book detail by ASIN including authors, narrators, series, pricing, and library status.
 */
export const getBookDetail = query('unchecked', async (asin: string) => {
	const { fetch } = getRequestEvent();
	const response = await fetch(`/api/books/${encodeURIComponent(asin)}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch book ${asin}: ${response.status} ${response.statusText}`);
	}
	return v.parse(BookDetailSchema, await response.json());
});

// --- GET /api/books/{asin}/details ---

const AudibleRatingSchema = v.object({
	avg: v.nullable(v.number()),
	count: v.nullable(v.number())
});

const AudibleRatingsSchema = v.object({
	overall: AudibleRatingSchema,
	performance: AudibleRatingSchema,
	story: AudibleRatingSchema
});

const AudibleReviewSchema = v.object({
	author: v.nullable(v.string()),
	title: v.nullable(v.string()),
	body: v.nullable(v.string()),
	date: v.nullable(v.string()),
	overall: v.nullable(v.number()),
	performance: v.nullable(v.number()),
	story: v.nullable(v.number()),
	helpful_votes: v.nullable(v.number())
});

const AudibleRelatedSchema = v.object({
	asin: v.string(),
	title: v.string(),
	authors: v.array(v.string()),
	image_url: v.nullable(v.string())
});

const AudibleCategorySchema = v.object({
	id: v.number(),
	name: v.string()
});

const BookEnrichmentSchema = v.object({
	full_description: v.nullable(v.string()),
	tags: v.array(v.string()),
	categories: v.array(AudibleCategorySchema),
	ratings: AudibleRatingsSchema,
	editorial_reviews: v.array(v.string()),
	user_reviews: v.array(AudibleReviewSchema),
	related: v.array(AudibleRelatedSchema),
	enriched_at: v.nullable(v.string()),
	stale: v.boolean(),
	error: v.nullable(v.string())
});

export type AudibleRating = v.InferOutput<typeof AudibleRatingSchema>;
export type AudibleReview = v.InferOutput<typeof AudibleReviewSchema>;
export type AudibleRelated = v.InferOutput<typeof AudibleRelatedSchema>;
export type BookEnrichment = v.InferOutput<typeof BookEnrichmentSchema>;

export const getBookEnrichment = query('unchecked', async (asin: string) => {
	const { fetch } = getRequestEvent();
	const response = await fetch(`/api/books/${encodeURIComponent(asin)}/details`);
	if (!response.ok) {
		throw new Error(`Failed to fetch Audible details for ${asin}: ${response.status} ${response.statusText}`);
	}
	return v.parse(BookEnrichmentSchema, await response.json());
});

// --- POST /api/books/{asin}/refresh-details ---

export const refreshBookDetails = command('unchecked', async (asin: string) => {
	const { fetch } = getRequestEvent();
	const response = await fetch(`/api/books/${encodeURIComponent(asin)}/refresh-details`, {
		method: 'POST'
	});
	if (!response.ok) {
		throw new Error(`Failed to refresh Audible details for ${asin}: ${response.status} ${response.statusText}`);
	}
	return v.parse(BookEnrichmentSchema, await response.json());
});

// --- GET /api/series/{id} ---

/** A book within a series — a library item plus its sequence and ownership flag. */
const SeriesBookSchema = v.object({
	...LibraryItemSchema.entries,
	sequence: v.nullable(v.number()),
	in_library: v.boolean()
});

const SeriesDetailSchema = v.object({
	id: v.number(),
	asin: v.nullable(v.string()),
	title: v.string(),
	rule: RuleRefSchema,
	book_count: v.number(),
	owned_count: v.number(),
	avg_rating: v.nullable(v.number()),
	books: v.array(SeriesBookSchema)
});

export type SeriesBook = v.InferOutput<typeof SeriesBookSchema>;
export type SeriesDetail = v.InferOutput<typeof SeriesDetailSchema>;

/**
 * Fetch a series with all its books (owned or not) and per-book taste state.
 */
export const getSeriesDetail = query('unchecked', async (id: number) => {
	const { fetch } = getRequestEvent();
	const response = await fetch(`/api/series/${id}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch series ${id}: ${response.status} ${response.statusText}`);
	}
	return v.parse(SeriesDetailSchema, await response.json());
});

// --- Shared profile schemas ---

const ProfileBookSchema = v.object({
	asin: v.string(),
	title: v.string(),
	runtime_minutes: v.nullable(v.number()),
	percent_complete: v.number(),
	is_finished: v.nullable(v.boolean()),
	user_rating: v.nullable(v.number())
});

const ProfileStatsSchema = v.object({
	book_count: v.number(),
	avg_rating: v.nullable(v.number()),
	total_runtime_minutes: v.number(),
	total_runtime_hours: v.number()
});

const ProfileSchema = v.object({
	id: v.number(),
	asin: v.nullable(v.string()),
	name: v.string(),
	stats: ProfileStatsSchema,
	books: v.array(ProfileBookSchema)
});

export type ProfileBook = v.InferOutput<typeof ProfileBookSchema>;
export type ProfileStats = v.InferOutput<typeof ProfileStatsSchema>;
export type Profile = v.InferOutput<typeof ProfileSchema>;

// --- GET /api/authors/{id} ---

/**
 * Fetch author profile with library stats and their books in the user's library.
 */
export const getAuthorProfile = query('unchecked', async (id: number) => {
	const { fetch } = getRequestEvent();
	const response = await fetch(`/api/authors/${id}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch author ${id}: ${response.status} ${response.statusText}`);
	}
	return v.parse(ProfileSchema, await response.json());
});

// --- GET /api/books/{asin}/similar ---

const SimilarBookSchema = v.object({
	asin: v.string(),
	title: v.string(),
	authors: v.string(),
	runtime_hours: v.nullable(v.number()),
	similarity_score: v.nullable(v.number())
});

const SimilarBooksResponseSchema = v.object({
	items: v.array(SimilarBookSchema)
});

export type SimilarBook = v.InferOutput<typeof SimilarBookSchema>;
export type SimilarBooksResponse = v.InferOutput<typeof SimilarBooksResponseSchema>;

/**
 * Fetch books similar to the given ASIN by embedding cosine similarity.
 * Returns empty items array if the book has no embedding yet.
 */
export const getSimilarBooks = query('unchecked', async (asin: string) => {
	const { fetch } = getRequestEvent();
	const response = await fetch(`/api/books/${encodeURIComponent(asin)}/similar`);
	if (!response.ok) {
		throw new Error(`Failed to fetch similar books for ${asin}: ${response.status} ${response.statusText}`);
	}
	return v.parse(SimilarBooksResponseSchema, await response.json());
});

// --- GET /api/narrators/{id} ---

/**
 * Fetch narrator profile with library stats and their books in the user's library.
 */
export const getNarratorProfile = query('unchecked', async (id: number) => {
	const { fetch } = getRequestEvent();
	const response = await fetch(`/api/narrators/${id}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch narrator ${id}: ${response.status} ${response.statusText}`);
	}
	return v.parse(ProfileSchema, await response.json());
});
