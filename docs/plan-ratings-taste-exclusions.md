# Implementation Plan — Library Ratings & Taste Rules (include/exclude)

Phased, file-by-file. Each step lists the files to touch and a **verify** check.
Grounded against the codebase at `904ef7b`. Single-user (`user_id = 1`).

> Revised after independent review (2026-06-21). See **Review findings addressed** at the end.
> Key reversals from the first draft: ratings get their **own column** (sync owns `user_rating`),
> rules support **include and exclude**, the scoring engine **is** filtered, and entity
> include/exclude is a **first-class Library-route action** (not an optional book-detail extra).

## Decisions locked in
- **Rating = integer 1–5**, clear = `NULL`. Stored in a **new** `user_libraries.user_manual_rating`
  column — **not** `user_rating`, which Audible sync overwrites with the public average
  (`sync/audible.py:239,251`). Validate range in the route (no DB CHECK precedent; matches `search.py:20`).
- **Manual rating feeds taste/scoring** at the top of the rating-priority chain:
  `user_manual_rating > goodreads my_rating > user_rating (Audible avg) > is_finished`.
- **Mutation verb = `PUT`** (no `PATCH` anywhere; precedent `PUT /api/taste/profile`).
- **Rules have a `mode`: `exclude` | `include`.** Include is an explicit override so a user can keep one
  title/author inside a broadly-excluded genre. **Precedence:** a `title` rule wins outright; otherwise
  a book is excluded iff some entity rule excludes it **and** no entity rule includes it.
- **Rules affect taste generation, the taste vector, AND all recommendation surfaces** (`scoring.py`
  source signals included — it is **not** left untouched), resolved through one helper.
- **Include/exclude is driven from the Library card** for the title and for each
  author / narrator / genre(category) / series on that book. The book-detail page is an optional
  secondary surface (Phase 4).

## Conventions to mirror
- Routes: `@router.<verb>` in the existing route module, `with get_cursor() as cur:` (commits on
  success), `RETURNING` for writes, `HTTPException` for errors, Pydantic `BaseModel` bodies
  (`routes/taste.py:16`). In tests, patch the **route module's** symbol, e.g.
  `audiblimey.api.routes.library.get_cursor`.
- Remote: `query(...)` for GET, `command('unchecked', async (arg) => { ...fetch(method) })` for
  mutations (`taste.remote.ts:65-77`); refetch with `.updates(theQuery)` (`taste/+page.svelte:35`).
- Tests: per-file `FakeCursor` (substring-matches SQL → returns hand-built tuples) + `fake_get_cursor`
  + `@patch`. Multi-cursor routes use a counter `side_effect` (`test_taste_routes.py:112-124`).
  No `conftest.py`, no DB, no JS test runner. Run: `python -m pytest tests/ -v` and `npm run check`.
- **Column-arity caution:** adding a `SELECT` column breaks positional-unpack `FakeCursor` fixtures.
  Every step that widens a query lists the fixtures to update.

---

## Phase 1 — Ratings (independent, shippable)

### 1.1 Migration — manual rating column
**File (new):** `db/migrations/003_user_manual_rating.sql`
```sql
ALTER TABLE user_libraries ADD COLUMN user_manual_rating DECIMAL(3,1);  -- 1.0–5.0 or NULL; user's one-click rating
```
- Distinct from `user_rating` (Audible public average, written by sync). Sync never touches this column.
- Auto-runs on a **fresh** DB (compose mounts `./db/migrations` → `docker-entrypoint-initdb.d`,
  `docker-compose.yml:13`). Existing dev volume: `psql -h localhost -U audiblimey -d audiblimey -f db/migrations/003_user_manual_rating.sql`.
- Verify: `\d user_libraries` shows `user_manual_rating`.

### 1.2 Backend — `PUT /api/library/{asin}/rating`
**File:** `audiblimey/api/routes/library.py`
- Pydantic body `class RatingBody(BaseModel): rating: int | None`.
- Route (after `get_library`):
  ```python
  @router.put("/library/{asin}/rating")
  async def set_rating(body: RatingBody, asin: str = Path(..., min_length=1)):
      if body.rating is not None and not (1 <= body.rating <= 5):
          raise HTTPException(422, "rating must be an integer 1–5 or null")
      with get_cursor() as cur:
          cur.execute("""
              UPDATE user_libraries ul SET user_manual_rating = %s
              FROM books b
              WHERE ul.book_id = b.id AND b.asin = %s AND ul.user_id = %s
              RETURNING ul.user_manual_rating
          """, (body.rating, asin, 1))
          row = cur.fetchone()
      if not row:
          raise HTTPException(404, f"No library entry for ASIN {asin}")
      return {"asin": asin, "user_manual_rating": float(row[0]) if row[0] is not None else None}
  ```
  - Use `if row[0] is not None` — **not** `if row[0]` (would mis-handle a future 0).
- Verify: `python -m pytest tests/test_library_routes.py -v`

### 1.3 Engine — manual rating priority + sync-safety guard
**File:** `audiblimey/engine/taste.py`
- `compute_taste_vector` (`:60`): add `ul.user_manual_rating` to the `SELECT`; in the Python priority
  chain prefer it first (`manual > gr_rating > user_rating > is_finished`).
- `build_profile_context` top-books (`:137,149-150`): `COALESCE(ul.user_manual_rating, gr.my_rating, ul.user_rating, CASE WHEN ul.is_finished THEN 3.5 END)`.

**File:** `audiblimey/engine/scoring.py`
- `get_series_progress` (`:197`): `AVG(COALESCE(ul.user_manual_rating, ul.user_rating))` for series rating.

**Sync stays as-is** (writes only `user_rating`) — add a guard test (1.4) asserting the sync upsert never
references `user_manual_rating`, so a future edit can't reintroduce the clobber.
- Verify: `python -m pytest tests/test_taste.py tests/test_scoring.py -v`

### 1.4 Backend tests
**File:** `tests/test_library_routes.py` — `TestSetRating`: set→200 (`FakeCursor` key `"RETURNING"` →
`[(Decimal("4"),)]`), clear→`null` (`[(None,)]`, assert `is None` not `0`), `0`/`6`→422, missing→404.
**File:** `tests/test_taste.py` — update existing `compute_taste_vector`/`build_profile_context` fixtures
for the **new column arity**; add one case proving `user_manual_rating` outranks the others.
**File:** `tests/test_audible_sync.py` — guard: the library upsert SQL string contains `user_rating` and
**not** `user_manual_rating`.
- Verify: `python -m pytest tests/ -v`

### 1.5 Frontend — remote + card stars
**File:** `src/lib/api/library.remote.ts`
- Add `user_manual_rating: v.nullable(v.number())` to `LibraryItemSchema` (`:8-19`).
- Add `setRating` (mirror `updateTasteProfile`):
  ```ts
  export const setRating = command('unchecked', async (a: { asin: string; rating: number | null }) => {
      const { fetch } = getRequestEvent();
      const r = await fetch(`/api/library/${encodeURIComponent(a.asin)}/rating`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rating: a.rating }) });
      if (!r.ok) throw new Error(`Failed to set rating: ${r.status} — ${await r.text()}`);
      return v.parse(v.object({ asin: v.string(), user_manual_rating: v.nullable(v.number()) }), await r.json());
  });
  ```
**File:** `src/lib/components/BookCard.svelte`
- Add `user_manual_rating?: number | null` to `BookCardData` and opt-in props
  `onRate?: (r: number) => void`, `onClearRating?: () => void`. Render an editable ★1–5 row + clear
  **only when `onRate` is set** (keeps it off the `PersonProfile` reuse). The stars reflect
  `user_manual_rating`; keep the existing `user_rating` ★ as a separate muted "Audible avg" if shown.
**File:** `src/routes/library/+page.svelte`
- `async function rate(asin, r) { await setRating({ asin, rating: r }).updates(libraryQuery); }`
  and pass `onRate`/`onClearRating` to `<BookCard>`.
- Also add `user_manual_rating` to the route's `GET /library` payload (1.2 area / Phase 2.6 SELECT).
- Verify: `npm run check`

### Acceptance measure (objective pass/fail)
**Automated:** `python -m pytest tests/ -v` green (incl. `TestSetRating`, the manual-rating-priority taste
case, the sync guard test, and **all pre-existing cases** after fixture-arity updates); `npm run check` → 0 errors.

**End-to-end** (DB up, backend on :8000; `API=http://localhost:8000`, `ASIN`=any owned title):

| # | Action | Pass condition |
|---|--------|----------------|
| 1 | `PUT $API/api/library/$ASIN/rating -d '{"rating":4}'` | `200`, `user_manual_rating == 4.0` |
| 2 | `GET $API/api/library?search=<title>` | item's `user_manual_rating == 4.0`; `user_rating` (Audible avg) **unchanged** |
| 3 | `PUT … -d '{"rating":null}'` then read back | `200`, `user_manual_rating == null` (not `0`) |
| 4 | `PUT … -d '{"rating":6}'` and `0` | `422` |
| 5 | unknown ASIN | `404` |
| 6 | **Sync-safety:** re-run a library sync (or inspect the upsert) | `user_manual_rating` retained; only `user_rating` rewritten |

**PASS** = automated green + rows 1–6 hold (notably #2/#6: manual rating survives sync).

---

## Phase 2 — Taste rules backend (include / exclude)

### 2.1 Migration
**File (new):** `db/migrations/004_taste_rules.sql`
```sql
CREATE TABLE taste_rules (
    id BIGSERIAL PRIMARY KEY,
    user_id   BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope     VARCHAR(10) NOT NULL CHECK (scope IN ('title','author','narrator','category','series')),
    entity_id BIGINT NOT NULL,                 -- books.id for 'title'; else authors/narrators/categories/series .id
    mode      VARCHAR(8) NOT NULL DEFAULT 'exclude' CHECK (mode IN ('exclude','include')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, scope, entity_id)
);
CREATE INDEX idx_taste_rules_user ON taste_rules (user_id);
CREATE TRIGGER trg_taste_rules_updated_at
    BEFORE UPDATE ON taste_rules FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```
- `entity_id` is polymorphic → no FK (orphan-on-entity-delete accepted; not GC'd in v1).
- Existing dev volume: apply manually via `psql … -f db/migrations/004_taste_rules.sql`.
- Verify: `\d taste_rules`.

### 2.2 Effective-exclusion helper (single source of truth, with include precedence)
**File:** `audiblimey/engine/taste.py`
```python
def excluded_book_ids(cursor, user_id: int) -> set[int]:
    """book_ids effectively excluded after include/exclude precedence.

    title rule wins; else excluded iff (entity exclude) AND NOT (entity include).
    """
    cursor.execute("""
        WITH rule_books AS (
            SELECT entity_id AS book_id, scope, mode FROM taste_rules WHERE user_id=%s AND scope='title'
            UNION ALL SELECT ba.book_id, t.scope, t.mode FROM taste_rules t JOIN book_authors   ba ON ba.author_id  =t.entity_id WHERE t.user_id=%s AND t.scope='author'
            UNION ALL SELECT bn.book_id, t.scope, t.mode FROM taste_rules t JOIN book_narrators bn ON bn.narrator_id=t.entity_id WHERE t.user_id=%s AND t.scope='narrator'
            UNION ALL SELECT bc.book_id, t.scope, t.mode FROM taste_rules t JOIN book_categories bc ON bc.category_id=t.entity_id WHERE t.user_id=%s AND t.scope='category'
            UNION ALL SELECT bs.book_id, t.scope, t.mode FROM taste_rules t JOIN book_series    bs ON bs.series_id  =t.entity_id WHERE t.user_id=%s AND t.scope='series'
        ), agg AS (
            SELECT book_id,
                bool_or(scope='title'  AND mode='exclude') AS te,
                bool_or(scope='title'  AND mode='include') AS ti,
                bool_or(scope<>'title' AND mode='exclude') AS ee,
                bool_or(scope<>'title' AND mode='include') AS ei
            FROM rule_books GROUP BY book_id
        )
        SELECT book_id FROM agg WHERE te OR (NOT te AND NOT ti AND ee AND NOT ei)
    """, (user_id,)*5)
    return {r[0] for r in cursor.fetchall()}
```
- Factor the `te/ti/ee/ei → excluded?` decision into a tiny pure function `_is_excluded(flags)` so the
  precedence is unit-testable without a DB (`FakeCursor` can't prove SQL filters).
- Callers pass the set to SQL as a `bigint[]` and filter with `<> ALL(%s)` / `= ANY(%s)`.

### 2.3 Taste engine filtering
**File:** `audiblimey/engine/taste.py`
- Add `excluded_ids: set[int] | None = None` to `compute_taste_vector` and `build_profile_context`
  (resolve via `excluded_book_ids` if `None`); `generate_taste_profile` resolves **once** and passes both.
- Add `AND ul.book_id <> ALL(%s)` to all 5 sites: vector (`:60`, filters before 1536-float
  `embedding::text` is fetched), top-books (`:126`), genres (`:166`), runtime (`:181`), completion (`:197`).
- Keep anchor substrings (`"embedding IS NOT NULL"`, `"HAVING"`, `"GROUP BY c.name"`, `"PERCENTILE_CONT"`,
  `"is_finished THEN 1"`) so `test_taste.py` keeps matching.
- Verify: `python -m pytest tests/test_taste.py -v`

### 2.4 Scoring engine filtering (source signals — finding 2)
**File:** `audiblimey/engine/scoring.py` — exclusions must remove excluded books from preference
signals, not just hide candidates.
- Add `excluded_ids: set[int] | None = None` to `get_author_scores`, `get_narrator_scores`,
  `get_series_progress`, `get_negative_signals`. Default `None` → resolve via `excluded_book_ids` (each
  opens its own cursor; resolve inside, or accept the set from the caller — prefer caller-passed to
  resolve once per request).
- Add `AND b.id <> ALL(%s)` to `get_author_scores` (`:93`), `get_narrator_scores` (`:144`), and the
  series CTE join `get_series_progress` (`:200`, on `bs.book_id`).
- `get_negative_signals` (`:239`) joins only `goodreads_books`; add
  `LEFT JOIN book_isbn_asin_map m ON m.goodreads_book_id=gb.id LEFT JOIN books b ON b.asin=m.asin`
  and `AND (b.id IS NULL OR b.id <> ALL(%s))` so an excluded author's abandoned-shelf penalty is also dropped.
- Verify: `python -m pytest tests/test_scoring.py -v`

### 2.5 Recommendation suppression — all three surfaces (finding 7)
**File:** `audiblimey/api/routes/recommendations.py` — resolve `excluded` once per request and pass to
scoring helpers **and** filter candidates.
- `get_recommendations`: candidate query (`:44-58`) gains `AND r.book_id <> ALL(%s)`; pass `excluded_ids`
  into the four `get_*` calls (`:37-40`).
- `get_series_recommendations` (`:122`): pass `excluded_ids` to `get_series_progress`; next-book query
  (`:136-153`) gains `AND b.id <> ALL(%s)` so excluded next books aren't suggested.
- `get_recommendation_detail` (`:175`): after fetching `book_id`, if it's in `excluded` → `404`; pass
  `excluded_ids` into the `get_*` calls (`:196-199`).
- Verify: `python -m pytest tests/test_recommendations_routes.py -v` (new, 2.8).

### 2.6 Rules API
**File:** `audiblimey/api/routes/taste.py`
- `GET /taste/rules` → active rules grouped by scope, each `{id, entity_id, mode, label}` (label via a
  join to the entity table per scope). Used by both the Taste-page list and as a lookup.
- `PUT /taste/rules` → body `{scope, entity_id, mode}` (Pydantic; validate scope∈5, mode∈{exclude,include}).
  **Idempotent + returns the row** (finding 5):
  ```sql
  INSERT INTO taste_rules (user_id, scope, entity_id, mode) VALUES (%s,%s,%s,%s)
  ON CONFLICT (user_id, scope, entity_id) DO UPDATE SET mode = EXCLUDED.mode, updated_at = NOW()
  RETURNING id, mode
  ```
  (so re-PUTting an existing rule still returns `{id, mode}`, and flips exclude↔include).
- `DELETE /taste/rules/{rule_id}` → clears the override: `DELETE … WHERE id=%s AND user_id=%s RETURNING id`; 404 if none.

### 2.7 Library payload + filter (findings 1 & 4)
**File:** `audiblimey/api/routes/library.py` (`get_library`)
- Resolve `excluded = excluded_book_ids(cur, 1)` once.
- Add a `taste` filter param `Query(None, pattern="^(all|included|excluded)$")`:
  `included` → `AND ul.book_id <> ALL(%s)`; `excluded` → `AND ul.book_id = ANY(%s)`.
- Extend each item with everything the card needs to act and to delete the *right* rule:
  - `book_id`, `user_manual_rating`, `taste_excluded` (effective; `book_id ∈ excluded`).
  - `title_rule`: `{id, mode} | null` — the `scope='title'` rule for this book.
  - `authors_ref`, `narrators_ref`, `categories`, `series`: arrays of `{id, name, rule}` where
    `rule = {id, mode} | null` is the matching `scope=<that>` rule. Build via correlated `json_agg`
    subqueries that LEFT JOIN `taste_rules` (mirrors the existing `string_agg` author/narrator subqueries).
  - Keep the existing `authors`/`narrators` **strings** for display + search highlight (don't break them).
- Perf: ≤100 paginated rows; a few `json_agg` subqueries each, all index-backed
  (`idx_book_authors_author`, etc., + `idx_taste_rules_user`). Acceptable; documented.
- Verify: `python -m pytest tests/test_library_routes.py -v`

### 2.8 Backend tests
- **New `tests/test_recommendations_routes.py`**: patch the route's `get_cursor` **and** the four scoring
  helpers; cover `get_recommendations` (excluded candidate absent), `get_series_recommendations`
  (excluded series/next-book absent), `get_recommendation_detail` (excluded `book_id` → 404).
- **`tests/test_taste.py`**: exclusion-delta + a pure-function test of `_is_excluded` covering precedence
  (title-include over entity-exclude; entity-include over entity-exclude; title-exclude wins).
- **`tests/test_scoring.py`**: assert each `get_*` query string gained the `<> ALL` clause/param (use the
  recording cursor; the DB-backed `TestIntegration` stays skip-if-no-DB).
- **`tests/test_taste_routes.py`** `TestTasteRules`: PUT new (200 `{id,mode}`), PUT existing flips mode and
  still returns the row, invalid scope/mode → 422, GET shape, DELETE 200 + 404.
- **`tests/test_library_routes.py`**: update `TestGetLibrary` fixtures for the new columns/json arrays
  (keep `"b.asin, b.title"` substring); add `taste=excluded`/`taste=included` filter tests.
- Verify: `python -m pytest tests/ -v`

### Acceptance measure (objective pass/fail)
**Automated:** `python -m pytest tests/ -v` green (new reco-routes file, taste-rule routes, scoring
`<> ALL` assertions, `_is_excluded` precedence cases, updated library fixtures).

**End-to-end** (DB up, backend on :8000). **Setup:** `GET /api/recommendations` → `total=R0`; pick item
`A` (`asin`, `book_id=BID`). Pick a rated+embedded title `T` (`book_id=TID`) with no other rules touching it.

1. **Reco suppression (immediate, robust):** `PUT {scope:title, entity_id:BID, mode:exclude}` →
   `GET /api/recommendations` → `A.asin` **absent** and `total < R0`. *(loosened from `R0-1` to tolerate
   duplicate candidate rows / overlapping rules — finding 8.)*
2. **All reco surfaces:** if `A` belonged to a series, it's gone from `/api/recommendations/series`;
   `GET /api/recommendations/{id_of_A}` → `404`.
3. **Library flag + filter:** `?taste=excluded` contains `A` with `taste_excluded=true` and a non-null
   `title_rule.id`; `?taste=included` omits `A`.
4. **Entity exclude:** `PUT {scope:author, entity_id:AID}` (author with `K` owned books) → `?taste=excluded`
   flags those `K`; each flagged item's `authors_ref` entry for `AID` has `rule.mode=="exclude"`.
5. **Include override (finding 6):** with the author rule active, `PUT {scope:title, entity_id:<one of
   the K>, mode:include}` → that one title now `taste_excluded=false`; the other `K-1` stay excluded.
6. **Taste-engine metric:** no rules → `POST /api/taste/generate` → `books_included=B0`. Add
   `{scope:title, entity_id:TID, mode:exclude}`, regenerate → `books_included == B0-1` (deterministic for
   one isolated rated+embedded title). Add the include override back → `== B0`.
7. **Scoring signal removed (finding 2):** exclude an author who has Goodreads-rated books, then inspect
   `GET /api/recommendations` `score_breakdown` for any surviving candidate → no `author_rating`
   component sourced from the excluded author. *(Confirms source-signal filtering, not just row hiding.)*
8. **Reversibility:** `DELETE` each rule → `total==R0`; `?taste=excluded` empty; regenerate → `B0`.

**PASS** = suite green + 1–8 hold (esp. #5 include override, #6 `B0→B0-1→B0`, #7 signal removal).

---

## Phase 3 — Frontend (Library-route include/exclude)

### 3.1 Remote functions
**File:** `src/lib/api/library.remote.ts`
- Extend `LibraryItemSchema`: `book_id`, `user_manual_rating`, `taste_excluded`,
  `title_rule: v.nullable(v.object({ id: v.number(), mode: v.string() }))`, and
  `authors_ref/narrators_ref/categories/series: v.array(v.object({ id, name, rule: v.nullable(...) }))`.
- Add the `taste` param to `getLibrary`.

**File:** `src/lib/api/taste.remote.ts`
- `getTasteRules = query(...)`; `putTasteRule = command('unchecked', async (r:{scope,entity_id,mode}) => PUT)`;
  `deleteTasteRule = command('unchecked', async (id:number) => DELETE)`.
- Verify: `npm run check`

### 3.2 Card controls + badge (finding 1 & 4)
**File:** `src/lib/components/BookCard.svelte`
- Extend `BookCardData` with the new fields. Add an opt-in `onRule?: (r:{scope,entity_id,mode}|{deleteId:number}) => void`
  callback (plus the Phase-1 rating props).
- Primary one-click **"Exclude from taste"** toggles the **title** rule: if `title_rule` is null →
  `onRule({scope:'title', entity_id:book_id, mode:'exclude'})`; if it exists → `onRule({deleteId:title_rule.id})`.
- A compact **"Taste ▾"** menu lists the title + each `authors_ref`/`narrators_ref`/`categories`/`series`
  entry with its current state (from each entry's `rule`), offering **Exclude / Include / Clear**:
  - Exclude/Include → `onRule({scope, entity_id, mode})`; Clear → `onRule({deleteId: entry.rule.id})`.
  - This is what makes include-overrides reachable per finding 6 (e.g. keep one author inside an excluded genre).
- Show a muted **"Excluded from taste"** badge when `taste_excluded` (reuse `Finished` badge style).

**File:** `src/routes/library/+page.svelte`
- Add a **Taste: All / Included / Excluded** filter (mirror the `statuses` group), bound to `taste` state.
- `async function applyRule(r) { const cmd = 'deleteId' in r ? deleteTasteRule(r.deleteId) : putTasteRule(r);
  await cmd.updates(libraryQuery); }` and pass `onRule={applyRule}` to each card.
- Verify: `npm run check`

### 3.3 Taste-page rules section
**File:** `src/routes/taste/+page.svelte`
- Below the profile, an "Taste rules" section from `getTasteRules()`, grouped by `mode` then scope
  (Excluded / Included), each entry one-click removable (`deleteTasteRule(id).updates(rulesQuery)`).
- One-line hint: rules affect recommendations immediately; the **profile text** updates on **Regenerate**
  (the vector/profile are cached, rebuilt only on `POST /taste/generate`).
- Verify: `npm run check`

### Acceptance measure (objective pass/fail)
No JS test runner → `npm run check` + **observable equality checks** (curl alongside the browser):
- `npm run check` → 0 errors.
- **(a) Title toggle:** one-click on a card adds/removes the badge **without reload**; `GET /api/taste/rules`
  reflects the title rule appearing/disappearing.
- **(b) Entity exclude + include override:** via the Taste menu, exclude a genre on a card → cards sharing
  that genre gain the badge; then **Include** one of them → its badge clears while the others keep theirs
  (matches Phase 2 #5).
- **(c) Filter counts match API:** Taste=Excluded → cards shown `==` `GET /api/library?taste=excluded`
  `total`, all badged; Taste=Included → none badged.
- **(d) Correct rule deleted:** removing a rule from the **Taste page** clears exactly that book/entity's
  badge in the Library view (proves the card/list carried the right `rule.id`, not a guess).

**PASS** = `npm run check` clean + (a)–(d) hold.

---

## Phase 4 — Book-detail surface (optional secondary)

The Library card already covers include/exclude; the book-detail page can offer the same per-chip control.
- `get_book_detail` (`library.py:122`): add a `categories` array `[{id,name}]` and attach each author/
  narrator/series/category's current `rule` (reuse the 2.7 subquery shape).
- `BookDetailSchema` + `src/routes/books/[asin]/+page.svelte`: per-chip Exclude/Include/Clear via the
  same `putTasteRule`/`deleteTasteRule`.
- Tests: extend book-detail fixtures for `categories`; one parametrized per-scope rule test.
- **Acceptance:** `pytest tests/test_library_routes.py` green; `npm run check` clean; from book-detail,
  excluding an author reproduces Phase 2 #4 + #7 for that author.

---

## Risks / notes
- **Column-arity test churn:** widening `compute_taste_vector` (manual rating) and `get_library`
  (book_id + json arrays) breaks positional `FakeCursor` fixtures — each affected step lists the fixtures
  to update; keep anchor substrings intact.
- **Include precedence is the subtle part:** the `te/ti/ee/ei` logic is centralized in `_is_excluded` and
  must be the *only* place that decides — both `excluded_book_ids` and any UI "effective state" derive from it.
- **Stale profile:** taste exclusions change recommendations immediately but the cached profile text only
  on Regenerate; surfaced in the Taste-page hint.
- **Orphan rules:** polymorphic `entity_id` has no FK; a re-synced entity can leave a stale rule.
  Acceptable for single-user v1.
- **`get_*_scores` ignore `user_id`** today (query all `goodreads_books`); the exclusion filter is by
  `book_id`, which is correct regardless — the pre-existing `user_id` gap is left as-is.

---

## Review findings addressed
| # | Finding (severity) | Where handled |
|---|--------------------|---------------|
| 1 | Entity exclude/include belongs on the **Library route**, not optional book-detail (High) | Decisions; 2.7 payload; 3.2 card menu; Phase 4 demoted to optional |
| 2 | Scoring still builds signals from excluded books (High) | 2.4 filters `get_author/narrator/series/negative` by `<> ALL`; acceptance 2#7 |
| 3 | Manual rating clobbered by Audible sync (High) | 1.1 new `user_manual_rating` column; 1.3 priority + sync guard; acceptance 1#2/#6 |
| 4 | Card lacks rule id / can't tell exclusion source (High) | 2.7 returns `title_rule` + per-entity `rule {id,mode}`; 3.2 uses them; acceptance 3(d) |
| 5 | `ON CONFLICT DO NOTHING` returns no row (Med) | 2.6 `DO UPDATE SET mode=EXCLUDED.mode RETURNING id, mode` |
| 6 | No include overrides (Med) | `mode` column + precedence (Decisions, 2.2 `_is_excluded`); 3.2 menu; acceptance 2#5 / 3(b) |
| 7 | Only `GET /api/recommendations` filtered (Med) | 2.5 also filters `/series` and `/{id}` detail; acceptance 2#2 |
| 8 | Brittle `total == R0-1` checks (Low) | Acceptance 2#1 loosened to `A absent AND total < R0`; #6 keeps exact only for the isolated controlled case |
