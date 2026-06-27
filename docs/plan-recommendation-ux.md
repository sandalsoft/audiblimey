# Implementation Plan — Recommendation & Series UX (grouping, images, exclusions, series links)

Phased, file-by-file. Each step lists the files to touch and a **verify** check.
Grounded against the codebase at `904ef7b`. Single-user (`user_id = 1`).

Covers four asks:
1. **Group same-series recommendations** into a single recommendation, denoted in the UI.
2. **Add cover images** to recommendation cards and Continue-Your-Series cards.
3. **Exclude authors / genres / titles / series** from being recommended (act from the rec card).
4. **Make each Continue-Your-Series card clickable** through to that series' detail page.

## Problem & current state

- **Recommendations are per-book.** `GET /api/recommendations` (`recommendations.py:26`) scores
  every `user_recommendations` row, sorts, then paginates (`:80-124`). When three unowned books
  of one series are recommended, the user sees three separate cards. Series recs are identifiable
  by `suggestion_type='series'` + `source_name = <series title>`.
- **No cover images anywhere on these surfaces.** `book_extended_data.image_url` is populated by
  sync (`sync/audible.py` `_best_image_url`), and `BookCard.svelte:88-106` already renders it with a
  lazy `<img>` + first-letter fallback. But the recommendation query (`recommendations.py:50`) and the
  series next-book query (`:152`) **don't select it**, and `RecommendationCard`/`SeriesCard` don't show it.
- **Exclusions exist but aren't reachable from a rec card.** `excluded_book_ids` + `taste_rules`
  (migration `004`) are live; `GET /api/recommendations` already filters excluded books (`:68`) and
  drops their scoring signals. What's missing for "exclude X from being recommended" is **entity ids on
  the rec payload** (author/genre/series/title) so the card can call the existing `PUT /api/taste/rules`.
  (The Library-route side of this is covered by `plan-ratings-taste-exclusions.md`; this plan adds the
  same control on the recommendation surface and reuses that plan's `putTasteRule`/`deleteTasteRule`.)
- **Series cards aren't clickable.** A `/series/[id]` detail page already exists, but
  `get_series_progress` (`scoring.py:178`) returns `series_title` and **drops `s.id`** (it's selected in
  the CTE at `:189` but not in the outer SELECT `:203`), so the dashboard has no id to link to.

## Decisions / assumptions (defaults — flip any in one line)

- **Grouping is server-side** (the ask is literally "a single recommendation"). Collapse only
  `suggestion_type='series'` rows sharing a series into one item carrying a `books[]` list; non-series
  recs are unchanged. Grouping happens **after scoring, before pagination**, so a group counts as one
  toward `total`. Group key = **`series_id`** (not title — titles can collide), resolved by joining the
  recommendation's `source_name` to `series.title`.
- **Group score = max of member scores**; group is ranked by that. `books[]` ordered by
  `book_series.sequence`.
- **Images come from `book_extended_data.image_url`** via `LEFT JOIN` (nullable). Frontend reuses the
  exact `<img loading="lazy" onerror=…>` + first-letter fallback pattern from `BookCard.svelte:88-106`.
- **Exclude-from-rec reuses `taste_rules`** (no new table/route). Title-exclude ⇒ `{scope:'title',
  entity_id:book_id}` (also removes it from recs via `excluded_book_ids`); author/genre/series map to
  `scope ∈ {author, category, series}`. After a rule is applied the rec query re-runs and the
  item/group disappears. **No new "dismiss"-style state** — exclusion is the mechanism.
- **Series link target = `/series/{series_id}`** (existing route). Whole `SeriesCard` becomes the link;
  the "next book" block keeps any nested actions as non-link affordances.
- **No scheduling** anywhere (project rule).

## Conventions to mirror

- Routes: `with get_cursor() as cur:`, positional `%s` params, `LEFT JOIN LATERAL` for the
  latest-price subquery (already used at `recommendations.py:60`). Add columns to existing SELECTs
  carefully — `FakeCursor` fixtures unpack positionally, so every widened query lists its fixtures to update.
- Remote: `query(...)` for GET, `command('unchecked', …)` for mutations, refetch with `.updates(q)`.
  Valibot schemas in `recommendations.remote.ts`; reuse `putTasteRule`/`deleteTasteRule` from
  `taste.remote.ts` (introduced in `plan-ratings-taste-exclusions.md` — that plan is a prerequisite for
  step 3.x; if not yet landed, add those two commands here).
- Tests: per-file recording `FakeCursor` (substring-match SQL → hand-built tuples) + `@patch` on the
  route module's `get_cursor` and the `get_*_scores` helpers (`test_recommendations_routes.py`). No DB,
  no JS runner. Run `python -m pytest tests/ -v` and `npm run check`.

---

## Phase 1 — Cover images (independent, shippable, lowest risk)

### 1.1 Backend — add `image_url` to both payloads
**File:** `audiblimey/api/routes/recommendations.py`
- `get_recommendations` query (`:50`): add `LEFT JOIN book_extended_data bx ON bx.book_id = r.book_id`
  and select `bx.image_url`. Add `"image_url": image_url` inside the `"book": {…}` dict (`:100-105`).
  Update the row unpack at `:82` for the new column.
- `get_series_recommendations` next-book query (`:152`): add the same `LEFT JOIN book_extended_data`
  on `b.id` and select `image_url`; include it in the `next_book` dict (`:176-185`).
- `get_recommendation_detail` (`:198`): add `image_url` to the detail SELECT + `book` dict (so the
  detail page can show the same cover).
- Verify: `python -m pytest tests/test_recommendations_routes.py -v`

### 1.2 Frontend — schemas + render
**File:** `src/lib/api/recommendations.remote.ts`
- `BookSchema` (`:7`): add `image_url: v.nullable(v.string())`.
- `NextBookSchema` (`:75`): add `image_url: v.nullable(v.string())`.
**File:** `src/lib/components/RecommendationCard.svelte` (the card rendered by the dashboard recs grid)
- Add a cover thumbnail using the **same** markup as `BookCard.svelte:88-106`: a fixed `h-… w-…`
  container, `<img src={book.image_url} loading="lazy" onerror={() => imageFailed = true}>` when
  `image_url && !imageFailed`, else the first-letter fallback. Keep a local `let imageFailed = $state(false)`.
**File:** `src/lib/components/SeriesCard.svelte`
- In the "Next book" block (`:64-97`), replace the `BookOpen` icon with the cover thumbnail (same
  pattern) when `series.next_book.image_url` is present; fall back to the existing `BookOpen` icon.
- Verify: `npm run check`

### Acceptance (objective)
- `pytest tests/ -v` green; `npm run check` → 0 errors.
- `GET /api/recommendations` items and `GET /api/recommendations/series[].next_book` include
  `image_url` (string or null). On the dashboard, cards with a cover render the image; cards without one
  show the first-letter fallback (no broken-image icon — `onerror` fallback fires).

---

## Phase 2 — Clickable Continue-Your-Series cards

### 2.1 Backend — surface `series_id`
**File:** `audiblimey/engine/scoring.py`
- `get_series_progress`: add `series_id` to the outer SELECT (`:203`, the value already exists as
  `s.id` in the `user_series` CTE) and to the row unpack (`:211`) + the returned dict (`:216`):
  `"series_id": series_id`.
- This dict flows verbatim into `GET /api/recommendations/series` (`recommendations.py:173`
  `item = {**sp}`), so no route change is needed.
- Verify: `python -m pytest tests/test_scoring.py -v` (update the `get_series_progress` fixture row
  arity — it now unpacks one more column).

### 2.2 Frontend — wrap the card in a link
**File:** `src/lib/api/recommendations.remote.ts`
- `SeriesItemSchema` (`:83`): add `series_id: v.number()`.
**File:** `src/lib/components/SeriesCard.svelte`
- Wrap the outer `<div class="rounded-xl …">` in `<a href="/series/{series.series_id}" class="block …">`
  (move hover styles to the anchor; add `hover:border-primary` for affordance, matching how
  `BookCard` links). Ensure any interactive controls inside the "next book" block don't sit inside a
  nested `<a>` (none currently do — it's display-only).
- Verify: `npm run check`

### Acceptance (objective)
- `pytest tests/ -v` green; `npm run check` → 0 errors.
- `GET /api/recommendations/series[].series_id` present. Clicking a Continue-Your-Series card navigates
  to `/series/{id}` and the detail page loads that series (matches `getSeriesDetail(id)`).

---

## Phase 3 — Group same-series recommendations

### 3.1 Backend — carry series identity + sequence on each rec row
**File:** `audiblimey/api/routes/recommendations.py`
- `get_recommendations` query (`:50`): for series-type rows, resolve the series the recommendation is
  about. Add:
  ```sql
  LEFT JOIN series sg ON sg.title = r.source_name AND r.suggestion_type = 'series'
  LEFT JOIN book_series bsg ON bsg.book_id = r.book_id AND bsg.series_id = sg.id
  ```
  and select `sg.id AS series_id, bsg.sequence AS series_sequence`. Update the row unpack (`:82`).
  *(Join on `source_name = series.title` because `source_name` is exactly the series title the
  generator wrote — `recommend.py` `_series_candidates`.)*

### 3.2 Backend — collapse after scoring, before pagination
**File:** `audiblimey/api/routes/recommendations.py`
- After the per-row scoring loop builds `scored` (`:80-117`) and **before** `scored.sort` / pagination
  (`:120-124`), fold series rows:
  - Partition `scored` into series items (`suggestion_type=='series'` **and** `series_id is not None`)
    and the rest.
  - Group series items by `series_id`. For each group build one item:
    ```python
    {
      "id": <id of the highest-scoring member>,        # stable handle for dismiss/detail
      "kind": "series_group",                          # discriminator for the frontend
      "series": {"id": series_id, "title": source_name, "count": len(members)},
      "score": max(m["score"] for m in members),
      "suggestion_type": "series",
      "source_name": source_name,
      "short_explanation": f"{len(members)} books from {source_name}",
      "books": [ {**m["book"], "sequence": m["series_sequence"], "score": m["score"],
                  "pricing": m["pricing"]} for m in sorted(members, key=sequence) ],
    }
    ```
    Single-member "groups" still render as a group of one (uniform shape) — or, to minimize churn,
    collapse only when `len(members) > 1` and leave singletons as normal `kind:"book"` items. **Default:
    collapse only when `>1`** (keeps single-book series recs looking like every other rec).
  - Tag every non-grouped item with `"kind": "book"`.
  - Re-form `scored = grouped_items + book_items`, then the existing `sort`/paginate runs unchanged
    (group `score` participates in the same ordering; `total` now counts a group as one).
- Keep `score_breakdown`/`explanation` on the **representative** member for the group (the dashboard's
  expand view can show the top book's reasoning); the per-book `books[]` entries carry their own `score`.
- Verify: `python -m pytest tests/test_recommendations_routes.py -v`

### 3.3 Frontend — schema + grouped card
**File:** `src/lib/api/recommendations.remote.ts`
- Introduce a discriminated item: extend the response to accept either the existing book item
  (`kind:"book"`, keep all current fields) or a `kind:"series_group"` item:
  ```ts
  const SeriesGroupItemSchema = v.object({
    id: v.number(), kind: v.literal('series_group'),
    series: v.object({ id: v.number(), title: v.string(), count: v.number() }),
    score: v.number(), suggestion_type: v.string(), source_name: v.string(),
    short_explanation: v.string(),
    books: v.array(v.object({ asin: v.string(), title: v.string(),
      image_url: v.nullable(v.string()), runtime_minutes: v.nullable(v.number()),
      runtime_hours: v.nullable(v.number()), sequence: v.nullable(v.number()),
      score: v.number(), pricing: PricingSchema })),
  });
  // RecommendationItemSchema gains kind: v.literal('book'); items = v.variant('kind', [book, group])
  ```
  Use `v.variant('kind', [...])` on the `kind` field. (Add `kind:"book"` to the backend book items in 3.2.)
**File:** `src/routes/+page.svelte` (recs grid)
- Branch on `item.kind`: `kind:"book"` → existing `<RecommendationCard>`; `kind:"series_group"` →
  new `<SeriesGroupCard>`.
**File (new):** `src/lib/components/SeriesGroupCard.svelte`
- Header denotes the group: e.g. **"{count} books from {series.title}"** with a link to
  `/series/{series.id}` (reuses Phase 2 routing). Lists each book (cover thumbnail from Phase 1,
  title, `Book {sequence}`, runtime, price). Visually distinct from single-book cards (e.g. a stacked
  list inside one bordered card) so the grouping reads clearly.
- Verify: `npm run check`

### Acceptance (objective)
- `pytest tests/ -v` green (new grouping cases: 3 series rows + 1 author row → 2 items, the series item
  has `kind:"series_group"`, `series.count==3`, `books` length 3 ordered by sequence, `score==max`;
  `total` counts the group once); `npm run check` → 0 errors.
- Dashboard: when ≥2 books of one series are recommended they appear as **one** card labeled
  "N books from <series>"; an author/narrator rec still appears as its own single card.

---

## Phase 4 — Exclude author / genre / title / series from a recommendation

> Prerequisite: `taste_rules` table + `PUT/DELETE /api/taste/rules` + `putTasteRule`/`deleteTasteRule`
> from `plan-ratings-taste-exclusions.md` (Phase 2 + 3.1). If unlanded, implement those two commands here.

### 4.1 Backend — entity refs (with ids) on the rec payload
**File:** `audiblimey/api/routes/recommendations.py`
- `get_recommendations`: extend each item's `"book"` with the ids needed to write a rule. Add three
  correlated aggregates to the query (mirror the existing narrators `ARRAY(...)` subquery at `:53-57`):
  - `authors_ref`: `json_agg(json_build_object('id', a.id, 'name', a.name))` via `book_authors`/`authors`.
  - `categories`: same via `book_categories`/`categories`.
  - `series_ref`: same via `book_series`/`series` (`{id, title}`).
  - plus `r.book_id` itself (for `scope:'title'`).
  Add these to the item dict as `book_id`, `authors_ref`, `categories`, `series_ref`. Update unpack.
- For **`series_group`** items (Phase 3), attach the same `series_ref` at the group level (it already
  has `series.id`/`title`) and the union of authors/categories across member books is **not** needed —
  excluding the series is the primary action; per-book title-exclude lives on each book row in the group.
- Verify: `python -m pytest tests/test_recommendations_routes.py -v`

### 4.2 Frontend — exclude controls on rec cards
**File:** `src/lib/api/recommendations.remote.ts`
- Add `book_id`, `authors_ref`, `categories`, `series_ref` to the book item schema (and `series_ref`
  to the group schema).
**File:** `src/lib/components/RecommendationCard.svelte` & `SeriesGroupCard.svelte`
- Add a compact **"Not interested ▾"** menu offering:
  - **Hide this title** → `putTasteRule({scope:'title', entity_id: book_id, mode:'exclude'})`
  - **Exclude author <name>** (per `authors_ref` entry) → `scope:'author'`
  - **Exclude genre <name>** (per `categories` entry) → `scope:'category'`
  - **Exclude series <title>** (per `series_ref` entry / the group's series) → `scope:'series'`
  Each calls the shared `applyRule` handler.
**File:** `src/routes/+page.svelte`
- `async function applyRule(r) { await putTasteRule(r).updates(getRecommendations); }` passed to both
  card types. Refetch drops the now-excluded item/group from the grid (backend already filters via
  `excluded_book_ids`).
- Verify: `npm run check`

### Acceptance (objective)
- `pytest tests/ -v` green; `npm run check` → 0 errors.
- From a rec card, "Exclude author X" issues `PUT /api/taste/rules {scope:'author', entity_id:X}`; the
  grid refetches and **every** rec by X disappears. "Exclude series S" removes the whole `series_group`
  card. "Hide this title" removes just that one. All are reversible by deleting the rule on the Taste page
  (`plan-ratings-taste-exclusions.md` Phase 3.3) — confirm one round-trip restores the rec.

---

## Files touched (summary)

| File | Phase | Change |
|------|-------|--------|
| `audiblimey/api/routes/recommendations.py` | 1,3,4 | select `image_url`; group series rows; entity-ref aggregates |
| `audiblimey/engine/scoring.py` | 2 | `get_series_progress` returns `series_id` |
| `src/lib/api/recommendations.remote.ts` | 1,2,3,4 | `image_url`, `series_id`, `series_group` variant, entity refs |
| `src/lib/components/RecommendationCard.svelte` | 1,4 | cover image; "Not interested" menu |
| `src/lib/components/SeriesCard.svelte` | 1,2 | cover image; wrap in `/series/{id}` link |
| `src/lib/components/SeriesGroupCard.svelte` | 3 | **new** — grouped series-rec card |
| `src/routes/+page.svelte` | 3,4 | branch on `item.kind`; `applyRule` handler |
| `tests/test_recommendations_routes.py` | 1,3,4 | image column, grouping, entity refs |
| `tests/test_scoring.py` | 2 | `get_series_progress` row arity + `series_id` |

## Risks / notes
- **Column-arity test churn:** every widened SELECT breaks positional `FakeCursor` fixtures —
  each step above names the file to update; keep existing anchor substrings (`"b.asin, b.title"`,
  `"is_dismissed = FALSE"`) so substring-matching fixtures still match.
- **`source_name → series.title` join (3.1):** assumes the generator wrote the exact series title as
  `source_name` (it does — `recommend.py` `_series_candidates`). If a title isn't unique across `series`,
  `LEFT JOIN series` could fan out; constrain with `DISTINCT ON`/`LIMIT 1` or prefer storing `series_id`
  on `user_recommendations` later. Acceptable for single-user v1; documented.
- **Variant schema (3.3):** the dashboard recs grid must handle both `kind` values; a missing `kind`
  on a legacy payload would fail valibot — backend always tags items in 3.2, so safe, but land 3.2 and
  3.3 together.
- **Exclusion is the only "negative" control here** — there's an existing `POST …/dismiss`; this plan
  doesn't touch it. "Not interested → exclude" is stronger (also strips scoring signal). If a softer
  per-rec dismiss is wanted alongside, it's a separate, smaller add.
- **Phase ordering:** 1 and 2 are independent and safe to ship first; 3 depends on 1 (group cards reuse
  the cover); 4 depends on the `taste_rules` plan and reuses 3's group schema.
