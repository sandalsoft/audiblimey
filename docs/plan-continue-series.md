# Implementation Plan — Continue Your Series + new-release discovery

Phased, file-by-file. Each step lists the files to touch and a **verify** check.
Grounded against the codebase at `904ef7b`. Single-user (`user_id = 1`).

## Problem & current state

**"Continue Your Series" already exists** on the Dashboard:
- `src/routes/+page.svelte` renders `<SeriesSection />`.
- `SeriesSection.svelte` → `getSeriesRecommendations()` (`recommendations.remote.ts`) →
  `GET /api/recommendations/series` (`recommendations.py:128`) → `get_series_progress`
  (`scoring.py:194`), rendered as `<SeriesCard>` (progress bar, urgency, next book + price).

It works, **but** the "next book" query (`recommendations.py:146-164`) can only surface a
book that is **already a row in `books`** (`book_series` → `books`, `WHERE ul.id IS NULL`).
`books` is populated **only** from the user's own library sync (`sync/audible.py` fetches
`1.0/library`). So the moment the user owns the latest book in a series, or a brand-new
entry is released, **there is no row to suggest** — Continue Your Series goes quiet exactly
when a new book exists to recommend.

The gap, and the user's ask: **search Audible for new entries in series the user has
started that aren't in their library yet**, ingest them, and let Continue Your Series
surface them.

## Decisions / assumptions (defaults — flip any in one line)

- **Keep the existing Continue-Your-Series UI**; the new work is **new-release discovery**
  surfaced through it (no rework of `SeriesSection`/`SeriesCard` beyond adding a refresh
  button). Existing ranking via `get_series_progress` is reused as-is.
- **Trigger = on-demand `POST /api/series/refresh`** (background job) **+ a dashboard
  button**. No scheduling (project rule). Optional Phase 3 folds the same ingestion into
  Audible sync.
- **Ingested catalog books get a `books` + `book_series` row but NO `user_libraries` row**
  (they're unowned). This makes `get_series_progress` see `total_in_series` grow and the
  existing next-book query find them — **zero change to the read path**.
- **"New entry" = an Audible product in a started series whose book isn't owned** (and,
  for display, flagged "newly released" when `release_date` is recent / `sequence` exceeds
  the user's max owned sequence).

## Conventions to mirror

- Background work = `BackgroundTasks` + a `sync_jobs` row, like `sync.py:start_audible_sync`
  + `sync/audible.py:run_sync`. `sync_jobs.job_type` CHECK already allows
  **`'suggestions_sync'`** (`001_initial_schema.sql:582`) — reuse it (no migration).
- Audible API access = `audible.Client(auth=Authenticator.from_dict(auth_data))` then
  `client.get("1.0/catalog/...", response_groups=…)` — exactly as `sync/audible.py:133,393`.
  Audible's catalog payload is **loosely documented**; mirror the defensive
  `try/except + logger.warning` + `# loosely documented` style already in that file.
- Engine/sync functions take a `cursor` (caller owns the transaction); per-item
  `SAVEPOINT` so one bad product doesn't poison the batch (`sync/audible.py:502-517`).
- Tests: recording `FakeCursor` + `@patch` on the module's `get_cursor`; patch the Audible
  `client` with a fake whose `.get(...)` returns canned dicts. Run
  `python -m pytest tests/ -v` and `npm run check`.

---

## Phase 1 — Catalog ingestion of new series entries

### 1.1 Refactor: extract book-core upsert from `store_book`
**File:** `audiblimey/sync/audible.py`
- `store_book` currently does (a) book upsert, (b) authors, (c) narrators, (d) series,
  (e) **user_libraries** upsert (`:359-379`). Extract (a)–(d) into a new
  `_store_book_core(cur, book_data) -> int | None` (returns `book_id`); `store_book` keeps
  its signature, calls `_store_book_core`, then does the `user_libraries` upsert. **Pure
  refactor — no behaviour change** (verify via existing `test_audible_sync.py`).
- This is the one allowed refactor: catalog ingestion must store a book + series **without**
  a library row, so the core must be reusable. It traces directly to the feature.
- Verify: `python -m pytest tests/test_audible_sync.py -v` (unchanged, still green).

### 1.2 New module — catalog ingestion
**File (new):** `audiblimey/sync/catalog.py`

```python
def _make_client(auth_data: dict):
    from audible import Authenticator, Client
    return Client(auth=Authenticator.from_dict(auth_data))

def fetch_catalog_product(client, asin: str) -> dict | None:
    """Fetch one catalog product with the response groups we store.
    Loosely documented API — returns None on any error."""
    # client.get(f"1.0/catalog/products/{asin}",
    #     response_groups="contributors,series,product_desc,media,price,relationships")

def fetch_series_products(client, owned_asin: str) -> list[dict]:
    """Enumerate all products in the series that owned_asin belongs to.

    Strategy (verify exact shape during impl, like _fetch_catalog_media):
      1. fetch_catalog_product(owned_asin) with response_groups including
         'relationships' → siblings carry {asin, sequence, relationship_type='series'}.
      2. for each sibling asin, fetch_catalog_product(asin) for full metadata.
    Returns list of product dicts (Audible 'product' shape store_book understands).
    """

def store_catalog_book(cur, book_data: dict) -> int | None:
    """Upsert a catalog (unowned) book: book + contributors + series, NO library row."""
    return _store_book_core(cur, book_data)   # imported from sync.audible
```

```python
def ingest_series_new_releases(user_id: int, job_id: int) -> None:
    """For every started series, fetch its catalog products and store any not in `books`.

    1. mark job running (sync_jobs).
    2. load auth_data (user_audible_accounts) — same as run_sync:457-483.
    3. find started series + a representative owned ASIN each:
         SELECT s.id, s.title, MIN(b.asin)
         FROM series s JOIN book_series bs ON bs.series_id=s.id
         JOIN books b ON b.id=bs.book_id
         JOIN user_libraries ul ON ul.book_id=b.id AND ul.user_id=%s
         GROUP BY s.id, s.title
    4. for each: fetch_series_products(client, owned_asin); for products whose asin is not
       already in `books`, store_catalog_book (SAVEPOINT per product). Count books_added.
    5. mark job completed (books_added) / failed, mirroring run_sync.
    """
```
- Designed for a `BackgroundTask` (like `run_sync`). Resolve everything by **owned ASIN**
  (more reliable than `series.asin`, which is often null).
- Verify: `python -m pytest tests/test_catalog.py -v` (new, 1.4).

### 1.3 Route — `POST /api/series/refresh` + status
**File (new):** `audiblimey/api/routes/series.py`
- `POST /series/refresh` — mirror `sync.py:start_audible_sync`: require an Audible account
  (400 if none), reject if a `suggestions_sync` job is already `running` (409), insert a
  `sync_jobs (job_type='suggestions_sync')` row, launch
  `background_tasks.add_task(ingest_series_new_releases, 1, job_id)`, return `{job_id, status}`.
- `GET /series/refresh/status` — latest `suggestions_sync` job (mirror `sync.py:get_sync_status`,
  filtered to `job_type='suggestions_sync'`).
**File:** `audiblimey/api/main.py` — register the new router (`app.include_router(series_router, prefix="/api")`).
- Verify: `python -m pytest tests/test_series_routes.py -v` (new, 1.4)

### 1.4 Tests
**File (new):** `tests/test_catalog.py` — fake `client.get` returns a canned series payload;
assert `ingest_series_new_releases` stores only **unowned** products (already-present ASIN
skipped), uses `store_catalog_book` (no `user_libraries` write — assert the executed SQL
never targets `user_libraries`), and updates the job row. Recording `FakeCursor`.
**File (new):** `tests/test_series_routes.py` — `POST /series/refresh` → 200 `{job_id}`;
409 when a `suggestions_sync` is running; 400 with no account; status shape. Patch the
route's `get_cursor` + `ingest_series_new_releases`.
**File:** `tests/test_audible_sync.py` — add a guard that `_store_book_core` does **not**
reference `user_libraries` and that `store_book` still does (locks the 1.1 refactor).
- Verify: `python -m pytest tests/ -v`

### Acceptance measure (objective pass/fail)
**Automated:** `python -m pytest tests/ -v` green (new catalog + series-route tests, the
refactor guard, all pre-existing); `npm run check` → 0 errors.

**End-to-end** (DB up with a synced library containing a started, *complete-in-DB* series;
backend :8000; a linked Audible account that actually has a newer entry):

| # | Action | Pass condition |
|---|--------|----------------|
| 1 | `POST /api/series/refresh` | `200`, `{job_id}` |
| 2 | `GET /api/series/refresh/status` until done | `status='completed'`, `books_added ≥ 0` |
| 3 | Inspect DB | new catalog books exist in `books` + `book_series`, with **no** `user_libraries` row |
| 4 | `GET /api/recommendations/series` | a series that was complete-in-DB now shows `owned_count < total_books` and a `next_book` = the newly-ingested entry |
| 5 | Second `POST …/refresh` | idempotent — no duplicate `books` rows (ON CONFLICT asin) |
| 6 | While one runs, `POST …/refresh` again | `409` |

**PASS** = automated green + rows 1–6 hold (esp. #3 no library row, #4 surfaced in Continue
Your Series, #5 idempotent).

---

## Phase 2 — Surface "new releases" on the Dashboard

The read path already reflects ingested books (Phase 1, #4). This phase adds the **button**
and a light "new" affordance.

### 2.1 Remote functions
**File:** `src/lib/api/recommendations.remote.ts` (or a new `series.remote.ts`)
- `refreshSeries = command('unchecked', …)` → `POST /api/series/refresh`.
- `getSeriesRefreshStatus = query(…)` → `GET /api/series/refresh/status` (for the
  in-progress/poll state; reuse the auto-poll approach from the recent sync work, commit
  `904ef7b`).
- Verify: `npm run check`

### 2.2 SeriesSection button + refresh
**File:** `src/lib/components/SeriesSection.svelte`
- Add a "Check for new releases" button in the section header:
  `async function refresh() { await refreshSeries().updates(getSeriesRecommendations); }`
  (optionally poll status, then re-fetch when `completed` — mirror the library sync
  auto-poll). Show a spinner/disabled state while running.
- Optional: tag a `<SeriesCard>` whose `next_book.sequence > max owned` or recent
  `release_date` with a small "New" badge (reuse the urgency-badge style in
  `SeriesCard.svelte:55-58`). Requires adding `release_date` to the next-book payload
  (`recommendations.py:147` SELECT + `NextBookSchema` in the remote) — small, optional.
- Verify: `npm run check`

### Acceptance measure (objective pass/fail)
- `npm run check` → 0 errors.
- **(a)** Clicking "Check for new releases" triggers the job and, on completion, the
  Continue-Your-Series grid updates **without reload** to show the new next-book (matches
  Phase 1 #4) — verify the card count/next-book equals `GET /api/recommendations/series`.
- **(b)** Button is disabled while a refresh is running; re-enables on completion.

**PASS** = `npm run check` clean + (a)–(b) hold.

---

## Phase 3 — (Optional) fold ingestion into Audible sync

In `sync/audible.py:run_sync`, after the library store loop completes, call
`ingest_series_new_releases`-style logic (reusing the same client/auth already loaded) so
every sync also discovers new series entries. Gated by a flag to keep library sync fast;
no scheduling.

---

## Files touched (summary)

| File | Phase | Change |
|------|-------|--------|
| `audiblimey/sync/audible.py` | 1 | extract `_store_book_core` from `store_book` (refactor) |
| `audiblimey/sync/catalog.py` | 1 | **new** — catalog fetch + `ingest_series_new_releases` |
| `audiblimey/api/routes/series.py` | 1 | **new** — `POST /series/refresh` + status |
| `audiblimey/api/main.py` | 1 | register series router |
| `tests/test_catalog.py`, `tests/test_series_routes.py` | 1 | **new** |
| `tests/test_audible_sync.py` | 1 | refactor guard |
| `src/lib/api/recommendations.remote.ts` | 2 | `refreshSeries`, status query |
| `src/lib/components/SeriesSection.svelte` | 2 | refresh button (+ optional "New" badge) |

## Risks / notes
- **Audible catalog API is loosely documented.** The exact `response_groups` and the
  relationships shape for "all books in a series" must be confirmed against a live response
  during implementation (the codebase already hedges this in `_fetch_catalog_media`). Keep
  the fetch defensive (`try/except`, return `None`/`[]`, log warnings) so a bad payload
  degrades to "no new releases" rather than failing the job.
- **No embeddings on ingested books:** new catalog books have `embedding = NULL`, so they
  won't appear in taste-similarity recs until `run_embedding_pipeline()` runs. Continue
  Your Series doesn't need embeddings (it's series-relationship based), so this feature
  works without OpenAI; the recommendation engine's similarity strategy
  (`plan-recommendation-engine.md` Phase 2) is what consumes them.
- **Shared module:** `sync/catalog.py` (`fetch_catalog_product`, `store_catalog_book`) is
  also the foundation for `plan-recommendation-engine.md` Phase 2 (catalog candidates by
  author/narrator). Build it here first; extend it there.
- **Orphan catalog books:** unowned books ingested here persist even if a series is later
  fully owned; harmless (they stop being "next" once owned). Not GC'd in v1.
</content>
