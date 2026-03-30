// SvelteKit remote function — server-side queries/commands bridging to FastAPI /api/import, /api/sync
import { query, command } from '$app/server';
import * as v from 'valibot';

// --- Import response schemas ---

const ImportStatsSchema = v.object({
	total_books: v.number(),
	inserted: v.number(),
	with_isbn: v.number(),
	with_rating: v.number(),
	negative_shelves: v.number(),
	positive_shelves: v.number()
});

const MatchStatsSchema = v.object({
	total_attempted: v.number(),
	matched_isbn_direct: v.number(),
	matched_openlibrary: v.number(),
	matched_fuzzy: v.number(),
	unmatched: v.number(),
	match_rate: v.number()
});

const UploadGoodreadsResponseSchema = v.object({
	status: v.string(),
	import: ImportStatsSchema,
	matching: MatchStatsSchema
});

export type UploadGoodreadsResponse = v.InferOutput<typeof UploadGoodreadsResponseSchema>;

// --- GET /api/import/stats ---

const ImportDashboardStatsSchema = v.object({
	total_goodreads_books: v.number(),
	total_matched: v.number(),
	total_unmatched: v.number(),
	match_rate: v.number(),
	rating_distribution: v.record(v.string(), v.number()),
	match_sources: v.record(v.string(), v.number()),
	top_shelves: v.record(v.string(), v.number())
});

export type ImportDashboardStats = v.InferOutput<typeof ImportDashboardStatsSchema>;

// --- GET /api/import/history ---

const ImportJobSchema = v.object({
	id: v.number(),
	type: v.string(),
	total_rows: v.nullable(v.number()),
	matched: v.nullable(v.number()),
	unmatched: v.nullable(v.number()),
	match_rate: v.number(),
	status: v.string(),
	started_at: v.nullable(v.string()),
	completed_at: v.nullable(v.string())
});

const ImportHistoryResponseSchema = v.object({
	imports: v.array(ImportJobSchema)
});

export type ImportJob = v.InferOutput<typeof ImportJobSchema>;
export type ImportHistoryResponse = v.InferOutput<typeof ImportHistoryResponseSchema>;

// --- POST /api/sync/audible ---

const SyncStartResponseSchema = v.object({
	job_id: v.number(),
	status: v.literal('started')
});

export type SyncStartResponse = v.InferOutput<typeof SyncStartResponseSchema>;

// --- GET /api/sync/status ---

const SyncJobStatusSchema = v.object({
	job_id: v.number(),
	job_type: v.string(),
	status: v.string(),
	started_at: v.nullable(v.string()),
	completed_at: v.nullable(v.string()),
	books_processed: v.nullable(v.number()),
	books_added: v.nullable(v.number()),
	books_updated: v.nullable(v.number()),
	error_message: v.nullable(v.string()),
	created_at: v.nullable(v.string())
});

const SyncNoJobsSchema = v.object({
	status: v.literal('no_syncs'),
	message: v.string()
});

const SyncStatusResponseSchema = v.union([SyncJobStatusSchema, SyncNoJobsSchema]);

export type SyncJobStatus = v.InferOutput<typeof SyncJobStatusSchema>;
export type SyncNoJobs = v.InferOutput<typeof SyncNoJobsSchema>;
export type SyncStatusResponse = v.InferOutput<typeof SyncStatusResponseSchema>;

// --- Remote functions ---

/**
 * Upload a Goodreads CSV file for import.
 * Constructs a FormData body — does NOT set Content-Type header
 * so the browser auto-sets the multipart boundary correctly.
 */
export const uploadGoodreads = command('unchecked', async (file: File) => {
	const formData = new FormData();
	formData.append('file', file);

	const response = await fetch('/api/import/goodreads', {
		method: 'POST',
		body: formData
	});

	if (!response.ok) {
		const detail = await response.text();
		throw new Error(`Goodreads import failed: ${response.status} ${detail}`);
	}

	const data = await response.json();
	return v.parse(UploadGoodreadsResponseSchema, data);
});

/**
 * Fetch current import statistics — totals, match rate, rating distribution, shelves.
 */
export const getImportStats = query(async () => {
	const response = await fetch('/api/import/stats');

	if (!response.ok) {
		throw new Error(`Failed to fetch import stats: ${response.status} ${response.statusText}`);
	}

	const data = await response.json();
	return v.parse(ImportDashboardStatsSchema, data);
});

/**
 * Fetch import job history (most recent 20).
 */
export const getImportHistory = query(async () => {
	const response = await fetch('/api/import/history');

	if (!response.ok) {
		throw new Error(`Failed to fetch import history: ${response.status} ${response.statusText}`);
	}

	const data = await response.json();
	return v.parse(ImportHistoryResponseSchema, data);
});

/**
 * Trigger an Audible library sync.
 * Returns 400 if no account configured, 409 if sync already running.
 */
export const startAudibleSync = command(async () => {
	const response = await fetch('/api/sync/audible', {
		method: 'POST'
	});

	if (!response.ok) {
		const detail = await response.text();
		throw new Error(`Audible sync failed: ${response.status} ${detail}`);
	}

	const data = await response.json();
	return v.parse(SyncStartResponseSchema, data);
});

/**
 * Get the latest sync job status, or { status: 'no_syncs' } when no jobs exist.
 */
export const getSyncStatus = query(async () => {
	const response = await fetch('/api/sync/status');

	if (!response.ok) {
		throw new Error(`Failed to fetch sync status: ${response.status} ${response.statusText}`);
	}

	const data = await response.json();
	return v.parse(SyncStatusResponseSchema, data);
});
