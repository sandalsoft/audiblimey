// SvelteKit remote function — server-side queries bridging to FastAPI /api/library, /api/books, /api/authors, /api/narrators
import { query } from '$app/server';
import * as v from 'valibot';

// --- Shared sub-schemas ---

/** A book in the user's library (list view). */
const LibraryItemSchema = v.object({
	asin: v.string(),
	title: v.string(),
	runtime_minutes: v.nullable(v.number()),
	runtime_hours: v.nullable(v.number()),
	percent_complete: v.number(),
	is_finished: v.boolean(),
	purchase_date: v.nullable(v.string()),
	user_rating: v.nullable(v.number()),
	authors: v.string(),
	narrators: v.string()
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
	async (params: { limit?: number; offset?: number; search?: string; status?: string } | undefined) => {
		const limit = params?.limit ?? 20;
		const offset = params?.offset ?? 0;
		const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
		if (params?.search) qs.set('search', params.search);
		if (params?.status) qs.set('status', params.status);

		const response = await fetch(`/api/library?${qs}`);
		if (!response.ok) {
			throw new Error(`Failed to fetch library: ${response.status} ${response.statusText}`);
		}
		return v.parse(LibraryResponseSchema, await response.json());
	}
);

// --- GET /api/books/{asin} ---

const PersonRefSchema = v.object({
	id: v.number(),
	asin: v.nullable(v.string()),
	name: v.string()
});

const SeriesRefSchema = v.object({
	id: v.number(),
	asin: v.nullable(v.string()),
	title: v.string(),
	sequence: v.nullable(v.number())
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
		is_finished: v.boolean(),
		purchase_date: v.nullable(v.string()),
		user_rating: v.nullable(v.number())
	})
);

const BookDetailSchema = v.object({
	asin: v.string(),
	title: v.string(),
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
	const response = await fetch(`/api/books/${encodeURIComponent(asin)}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch book ${asin}: ${response.status} ${response.statusText}`);
	}
	return v.parse(BookDetailSchema, await response.json());
});

// --- Shared profile schemas ---

const ProfileBookSchema = v.object({
	asin: v.string(),
	title: v.string(),
	runtime_minutes: v.nullable(v.number()),
	percent_complete: v.number(),
	is_finished: v.boolean(),
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
	const response = await fetch(`/api/authors/${id}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch author ${id}: ${response.status} ${response.statusText}`);
	}
	return v.parse(ProfileSchema, await response.json());
});

// --- GET /api/narrators/{id} ---

/**
 * Fetch narrator profile with library stats and their books in the user's library.
 */
export const getNarratorProfile = query('unchecked', async (id: number) => {
	const response = await fetch(`/api/narrators/${id}`);
	if (!response.ok) {
		throw new Error(`Failed to fetch narrator ${id}: ${response.status} ${response.statusText}`);
	}
	return v.parse(ProfileSchema, await response.json());
});
