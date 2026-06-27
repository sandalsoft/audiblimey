# Implementation Plan — Recommendation Engine (generate "books you'll enjoy")

Phased, file-by-file. Each step lists the files to touch and a **verify** check.
Grounded against the codebase at `904ef7b`. Single-user (`user_id = 1`).

## Problem & current state

The scoring + explainability engines already exist and work
(`engine/scoring.py`, `engine/explainability.py`), and the read routes
(`GET /api/recommendations`, `/series`, `/{id}`) already rank, filter (taste rules),
and explain recommendations. **But nothing populates `user_recommendations`.** The table
is read (`recommendations.py:48-72`) and never written, so the dashboard shows
"No recommendations yet" against an empty table.

So "implement the recommendation engine" = **build the generator** that fills
`user_recommendations` with unowned candidate books the user is likely to enjoy,
derived from their **purchases** (owned authors/narrators/series), **finish rate**
(finished → positive, abandoned → negative), and **ratings**
(`user_manual_rating` > Goodreads `my_rating` > Audible `user_rating`).

The scoring engine already turns ratings + finish signals into a weighted score; the
**taste vector** (`taste_profiles.taste_vector`, a rating-weighted embedding centroid)
already encodes ratings *and* finish-rate fallback. The generator's job is candidate
*selection + persistence*; the existing read route already re-scores and sorts.

## Decisions / assumptions (defaults — flip any in one line)

- **Candidate pool = both, phased.** Phase 1 generates from books **already in the DB**
  (unowned next-in-series, unowned books by liked authors/narrators, taste-vector
  similarity). Phase 2 fetches **fresh unowned candidates from the Audible catalog**
  (shares the catalog-ingestion module introduced in `plan-continue-series.md`). Phase 1
  ships standalone; until Phase 2, discovery is limited to books the DB already knows
  (e.g. catalog books ingested by the series feature).
- **Trigger = on-demand `POST /api/recommendations/generate`** (mirrors
  `POST /api/taste/generate`). No scheduling (project rule). Optional: also run during
  Audible sync (Phase 3, off by default).
- **Generator stores `confidence_score` + `score_breakdown` + `explanation_text`** on each
  row so the table is self-describing; the read route's on-the-fly re-scoring is left
  **unchanged** (it already recomputes from live signals).
- **Idempotent upsert** on the existing unique key `(user_id, book_id, suggestion_type,
  source_name)`; dismissed rows (`is_dismissed = TRUE`) are **not** resurrected.

## Conventions to mirror

- Engine module = pure functions taking a `cursor` (caller owns the transaction), like
  `engine/taste.py` / `engine/embeddings.py`. Route opens `with get_cursor() as cur:`.
- Reuse `excluded_book_ids(cur, 1)` (`engine/taste.py:60`) so taste-rule exclusions never
  become candidates — resolve once, pass down (same pattern as `recommendations.py:37-45`).
- Tests: per-file recording `FakeCursor` (substring-match SQL → hand-built tuples) +
  `fake_get_cursor` + `@patch` on the **module under test's** `get_cursor`
  (`test_recommendations_routes.py:14-60`). No DB, no JS runner. Run:
  `python -m pytest tests/ -v` and `npm run check`.
- Remote: `command('unchecked', …)` for POST, refetch with `.updates(query)`
  (`taste.remote.ts`, `recommendations.remote.ts`).

---

## Phase 1 — Generator over existing DB books (independent, shippable)

### 1.1 New engine module — candidate generation
**File (new):** `audiblimey/engine/recommend.py`

A single entry point plus one helper per strategy. All candidate queries:
- join `user_libraries` and keep only **unowned** books (`LEFT JOIN … WHERE ul.id IS NULL`),
- exclude taste-ruled books (`AND b.id <> ALL(%s::bigint[])` with `excluded_book_ids`),
- exclude books already dismissed by the user for that `(suggestion_type, source_name)`.

```python
def generate_recommendations(cursor, user_id: int = 1, client=None) -> dict:
    """Select unowned candidate books from purchase/finish/rating signals and
    upsert them into user_recommendations. Returns counts per strategy.

    client: optional OpenAI client, only used by the embedding strategy.
    """
    excluded = excluded_book_ids(cursor, user_id)
    candidates = []                      # list[(book_id, suggestion_type, source_name)]
    candidates += _series_candidates(cursor, user_id, excluded)
    candidates += _author_candidates(cursor, user_id, excluded)
    candidates += _narrator_candidates(cursor, user_id, excluded)
    candidates += _similar_candidates(cursor, user_id, excluded)   # taste-vector cosine
    # dedupe by (book_id, suggestion_type, source_name); upsert each
    return _persist(cursor, user_id, candidates)
```

Strategy queries (each returns unowned `book_id` + `source_name`):

- **`_series_candidates`** — next unowned book in every *started* series. Reuse the
  shape of `recommendations.py:146-164` (the `/series` next-book query) but across all
  started series in one query: `book_series` → `series` → `LEFT JOIN user_libraries`,
  `WHERE ul.id IS NULL` and the series has ≥1 owned book, ordered by `bs.sequence`,
  `DISTINCT ON (series_id)` for the next one. `suggestion_type='series'`,
  `source_name = series.title`. *(Finish-rate aware: a started series the user keeps
  finishing scores higher via `get_series_progress` urgency at read time.)*
- **`_author_candidates`** — unowned books by authors the user **rates well and finishes**.
  Source authors from `get_author_scores(user_id, excluded_ids=excluded)`
  (`scoring.py:88`), keep `weighted_score` above a floor and `has_negative=False`; find
  their unowned books in `books` via `book_authors`. `suggestion_type='author'`,
  `source_name = author.name`.
- **`_narrator_candidates`** — same against `get_narrator_scores` (`scoring.py:146`).
  `suggestion_type='narrator'`, `source_name = narrator.name`.
- **`_similar_candidates`** — pgvector cosine between the stored `taste_profiles.taste_vector`
  and unowned `books.embedding` (mirror the cosine query in `engine/search.py`), top N.
  `suggestion_type='similar'`, `source_name='Taste match'`. Skip silently if no taste
  vector exists yet (no error — other strategies still run).

`_persist` scores each candidate with the existing engine and upserts:
```python
author_scores   = get_author_scores(user_id, excluded_ids=excluded)
narrator_scores = get_narrator_scores(user_id, excluded_ids=excluded)
negatives       = get_negative_signals(user_id, excluded_ids=excluded)
series_prog     = get_series_progress(user_id, excluded_ids=excluded)
# for each candidate: look up asin/title, call score_recommendation(...),
# generate_score_breakdown(...), then:
INSERT INTO user_recommendations
    (user_id, book_id, suggestion_type, source_name, confidence_score,
     score_breakdown, explanation_text, generated_at)
VALUES (%s,%s,%s,%s,%s,%s,%s, NOW())
ON CONFLICT (user_id, book_id, suggestion_type, source_name) DO UPDATE SET
    confidence_score = EXCLUDED.confidence_score,
    score_breakdown  = EXCLUDED.score_breakdown,
    explanation_text = EXCLUDED.explanation_text,
    generated_at     = NOW()
WHERE user_recommendations.is_dismissed = FALSE   -- don't resurrect dismissed
```
- `score_breakdown` → `psycopg2.extras.Json(...)` (column is `JSONB`).
- Verify: `python -m pytest tests/test_recommend.py -v` (new, 1.3).

### 1.2 Route — `POST /api/recommendations/generate`
**File:** `audiblimey/api/routes/recommendations.py`
- Mirror `POST /api/taste/generate` (`taste.py:81`): open a cursor, call
  `generate_recommendations(cur, 1)`, return per-strategy counts + total. The embedding
  strategy needs `OPENAI_API_KEY` **only if** you later embed fresh candidates; Phase 1
  uses already-stored embeddings, so **no 503** — it degrades (skips `_similar`) when no
  taste vector exists. Return `{"generated": N, "by_type": {...}}`.
- Verify: `python -m pytest tests/test_recommendations_routes.py -v`

### 1.3 Tests
**File (new):** `tests/test_recommend.py` — recording `FakeCursor`; assert each strategy
query carries its anchor clauses (`ul.id IS NULL`, `<> ALL`), that `_persist` emits the
`ON CONFLICT … WHERE is_dismissed = FALSE` upsert, and that a candidate present in
`excluded` is filtered (structural, like `test_recommendations_routes.py`). Patch
`get_author_scores`/`get_narrator_scores`/`get_series_progress`/`get_negative_signals`
to return small fixtures.
**File:** `tests/test_recommendations_routes.py` — add `TestGenerate`: POST → 200 with
`generated` count; patch `recommend.generate_recommendations`.
- Verify: `python -m pytest tests/ -v`

### 1.4 Frontend — generate button + remote
**File:** `src/lib/api/recommendations.remote.ts`
```ts
export const generateRecommendations = command('unchecked', async () => {
  const { fetch } = getRequestEvent();
  const r = await fetch('/api/recommendations/generate', { method: 'POST' });
  if (!r.ok) throw new Error(`Failed to generate: ${r.status} — ${await r.text()}`);
  return v.parse(v.object({ generated: v.number() }), await r.json());
});
```
**File:** `src/routes/+page.svelte`
- Add a "Refresh recommendations" button near the heading:
  `async function regen() { await generateRecommendations().updates(recsQuery); }`.
- Update the empty-state copy (`+page.svelte:24-30`) to mention the button once a library
  exists ("Generate recommendations from your library").
- Verify: `npm run check`

### Acceptance measure (objective pass/fail)
**Automated:** `python -m pytest tests/ -v` green (new `test_recommend.py`, `TestGenerate`,
all pre-existing); `npm run check` → 0 errors.

**End-to-end** (DB up with a synced library + some ratings/finishes; backend :8000):

| # | Action | Pass condition |
|---|--------|----------------|
| 1 | `POST /api/recommendations/generate` | `200`, `generated > 0` |
| 2 | `GET /api/recommendations` | `total > 0`; items are **unowned** books; each has a `score_breakdown` |
| 3 | A highly-rated author with an unowned book in DB | that book appears with `suggestion_type='author'`, `source_name=<author>` |
| 4 | A started, incomplete series | its next unowned book appears with `suggestion_type='series'` |
| 5 | Exclude a candidate's title (`PUT /api/taste/rules` exclude), regenerate | that book is **absent** from the next generate + from `GET /api/recommendations` |
| 6 | Dismiss a rec (`POST …/dismiss`), regenerate | it stays dismissed (not resurrected) |
| 7 | An abandoned-author's book | absent or low-scored (negative signal applied) |

**PASS** = automated green + rows 1–7 hold (esp. #5 exclusion, #6 no-resurrect).

---

## Phase 2 — Fresh catalog candidates (depends on `plan-continue-series.md`)

Phase 1 can only recommend books already in `books`. To recommend genuinely new titles,
ingest unowned catalog books, embed them, then re-run the generator.

**Depends on** the catalog-ingestion primitives defined in `plan-continue-series.md`
(`audiblimey/sync/catalog.py`: `fetch_catalog_product`, `store_catalog_book`).

### 2.1 Fetch candidates by liked entities
**File:** `audiblimey/sync/catalog.py` (extend)
- `fetch_author_catalog(client, author_name, limit)` → `client.get("1.0/catalog/products",
  author=…, products_sort_by="-ReleaseDate", num_results=limit, response_groups="contributors,series,product_desc,media,price")`.
  *(Audible catalog params are loosely documented — verify response_groups during
  implementation, mirroring the `# loosely documented` caution in `sync/audible.py`.)*
- For the top-K liked authors/narrators (from `get_*_scores`), fetch and `store_catalog_book`
  each unowned result (book + contributors + series, **no** `user_libraries` row).

### 2.2 Embed then generate
**File:** `audiblimey/api/routes/recommendations.py` (generate route)
- Optional `?fetch_catalog=true` (default false): before generating, run 2.1 for the user's
  top liked authors/narrators, then `run_embedding_pipeline()` (`engine/embeddings.py`,
  already embeds only NULL-embedding books), then `generate_recommendations`. Requires
  `OPENAI_API_KEY` → `503` if absent **and** `fetch_catalog=true`.

### Acceptance measure
- `POST /api/recommendations/generate?fetch_catalog=true` ingests ≥1 unowned catalog book,
  embeds it, and it appears in `GET /api/recommendations` as `suggestion_type ∈
  {author,narrator,similar}`. `pytest`/`npm run check` green.

---

## Phase 3 — (Optional) generate during sync

After a successful Audible sync (`sync/audible.py:run_sync`), call
`generate_recommendations` (and optionally `run_embedding_pipeline` first) so the
dashboard is fresh post-sync. Off by default; gated behind a flag to keep sync fast.
No scheduling.

---

## Files touched (summary)

| File | Phase | Change |
|------|-------|--------|
| `audiblimey/engine/recommend.py` | 1 | **new** — candidate generation + persist |
| `audiblimey/api/routes/recommendations.py` | 1,2 | `POST …/generate` endpoint |
| `tests/test_recommend.py` | 1 | **new** — generator unit tests |
| `tests/test_recommendations_routes.py` | 1 | `TestGenerate` |
| `src/lib/api/recommendations.remote.ts` | 1 | `generateRecommendations` command |
| `src/routes/+page.svelte` | 1 | refresh button + empty-state copy |
| `audiblimey/sync/catalog.py` | 2 | extend with author/narrator catalog fetch |

## Risks / notes
- **Empty DB candidate pool:** Phase 1 only recommends books already present. With a
  library-only DB, `author`/`narrator`/`similar` strategies find little until the series
  feature (or Phase 2) ingests catalog books — call this out in the dashboard empty state.
- **Read route still re-scores:** the generator's stored `confidence_score` is currently
  cosmetic for ranking (route recomputes `score`). Left intentionally; a later step could
  read stored breakdowns to skip recompute.
- **`get_*_scores` ignore `user_id`** today (query all `goodreads_books`); pre-existing,
  left as-is — exclusion is by `book_id`, which is correct regardless.
- **Fuzzy series matching over-includes (`catalog.py:84`):** the candidate filter uses
  `name == target or target in name or name in target`, so substring hits pull in
  unrelated series (e.g. "Foundation" matches "Foundation and Empire" and any title
  containing "foundation"). Tracked here rather than the enrichment fix pass since it
  lives in catalog discovery. Tighten to exact/normalized match (or token-boundary
  match) when this plan's catalog step is implemented.
</content>
</invoke>
