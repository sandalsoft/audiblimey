# Implementation Plan — Library Pagination (jump to a specific page)

Phased, file-by-file. Each step lists the files to touch and a **verify** check.
Grounded against the codebase at `904ef7b`. Single-user (`user_id = 1`).

## Problem & current state

`GET /api/library` already supports `limit`/`offset` (`library.py:146-148`) and
returns `{items, total, offset, limit}`. The Library page already paginates with
**Previous / Next** buttons and a "Page X of Y" label (`library/+page.svelte:110-133`).

Two gaps versus the request ("browse to a **specific** page", "best practices"):

1. **No direct page navigation** — you can only step one page at a time.
2. **Page (and filter) state is component-local `$state`**, not in the URL. A refresh,
   bookmark, shared link, or browser Back/Forward all lose the current page and filters.

This plan adds numbered page navigation and moves page + filter state into the URL
query string (`?page=3&search=…&status=…&taste=…`), the standard SvelteKit pattern.

> Scope decision (recommended, used here): page **and** filters live in the URL so a
> shared/refreshed link reproduces exactly what the user saw. If you'd rather keep filters
> as local state and only put `page` in the URL, only steps 2–3 change (drop the filter
> params) — the rest stands.

## Conventions to mirror

- **No backend change needed.** `limit`/`offset` already do the work; the frontend converts
  `page → offset` as `offset = (page - 1) * PAGE_SIZE`. (Optional alt considered & rejected
  below.)
- Components live in `src/lib/components/*.svelte` (e.g. `BookCard.svelte`); pages use Svelte 5
  runes (`$state`, `$derived`) and SvelteKit remote functions via `.updates(query)`
  (`library/+page.svelte`, `taste/+page.svelte:35`).
- URL state in SvelteKit: read from `page.url.searchParams` (`$app/state`), write with
  `goto(url, { keepFocus: true, noScroll: false })` (`$app/navigation`). Check existing imports
  in sibling routes (`series/[id]/+page.svelte`, `import/+page.svelte`) for the project's
  `$app/state` vs `$app/stores` choice and match it.
- Tests: `python -m pytest tests/ -v` and `npm run check` (no JS test runner in repo).

---

## Phase 1 — Reusable Pagination component

### 1.1 New component
**File (new):** `src/lib/components/Pagination.svelte`

- Props: `currentPage: number`, `totalPages: number`, `onNavigate: (page: number) => void`.
- Render: **Previous**, a windowed list of numbered page buttons with ellipses, **Next**.
  - Window logic (common pattern): always show page 1 and `totalPages`; show
    `currentPage ± 1`; insert a non-clickable `…` where the sequence skips. Example for
    page 6 of 20: `‹ Prev  1 … 5 [6] 7 … 20  Next ›`.
  - Current page button is visually active and `aria-current="page"`; `…` is inert.
  - Previous disabled on page 1; Next disabled on last page (mirror existing disabled styles
    at `library/+page.svelte:117-118`).
- Styling: reuse the existing button classes already in the page so it looks identical
  (`rounded-lg border border-border bg-card px-3 py-2 …`, active = `bg-primary text-primary-foreground`).
- Accessibility: wrap in `<nav aria-label="Pagination">`; each number is a `<button>`.
- **Verify:** `npm run check` passes (types); render a few page/total combos mentally —
  `totalPages <= 1` renders nothing, small counts (≤7) render every page with no ellipsis,
  large counts collapse correctly at both ends and the middle.

---

## Phase 2 — Drive Library state from the URL

### 2.1 Read state from the URL
**File:** `src/routes/library/+page.svelte`

- Replace the local `offset`/`search`/`status`/`taste` `$state` (lines 9-12) with values
  **derived from the URL**:
  ```ts
  import { page } from '$app/state';          // match sibling routes' choice
  import { goto } from '$app/navigation';

  const PAGE_SIZE = 20;
  const params      = $derived(page.url.searchParams);
  const currentPage = $derived(Math.max(1, Number(params.get('page')) || 1));
  const search      = $derived(params.get('search') ?? '');
  const status      = $derived((params.get('status') ?? 'all') as Status);
  const taste       = $derived((params.get('taste')  ?? 'all') as Taste);
  const offset      = $derived((currentPage - 1) * PAGE_SIZE);
  ```
- `libraryQuery` (line 27) keeps the same shape; it now reads the derived values, so it
  re-runs automatically when the URL changes.

### 2.2 Write state to the URL
**File:** `src/routes/library/+page.svelte`

- Add one helper that builds the next URL and navigates, dropping default-valued params so
  the URL stays clean:
  ```ts
  function setParams(next: Partial<{ page: number; search: string; status: Status; taste: Taste }>) {
    const sp = new URLSearchParams(params);
    const apply = (k: string, v: string, def: string) => v === def ? sp.delete(k) : sp.set(k, v);
    if (next.page   !== undefined) apply('page', String(next.page), '1');
    if (next.search !== undefined) apply('search', next.search, '');
    if (next.status !== undefined) apply('status', next.status, 'all');
    if (next.taste  !== undefined) apply('taste',  next.taste,  'all');
    // Any filter change resets to page 1
    if (next.search !== undefined || next.status !== undefined || next.taste !== undefined) sp.delete('page');
    goto(`?${sp}`, { keepFocus: true, noScroll: next.page === undefined });
  }
  ```
- Wire the controls:
  - Search input `oninput` → `setParams({ search: e.currentTarget.value })`
    (debounce optional — see Phase 4; today it fires per keystroke, behavior unchanged).
  - Status buttons → `setParams({ status: s.value })`.
  - Taste buttons → `setParams({ taste: t.value })`.
- **Verify:** `npm run check`. Manually: typing in search updates `?search=…` and resets page;
  toggling filters updates the URL; Back/Forward restores prior page+filters.

### 2.3 Replace inline Prev/Next with the component
**File:** `src/routes/library/+page.svelte`

- Delete the inline pagination block (lines 110-133). Replace with:
  ```svelte
  {@const totalPages = Math.ceil(data.total / PAGE_SIZE)}
  <Pagination
    currentPage={Math.min(currentPage, Math.max(1, totalPages))}
    {totalPages}
    onNavigate={(p) => setParams({ page: p })}
  />
  ```
- Import `Pagination` alongside `BookCard` (line 3).
- **Verify:** clicking a page number loads that page and updates `?page=N`; Prev/Next still work;
  the active page is highlighted.

### 2.4 Guard out-of-range pages
**File:** `src/routes/library/+page.svelte`

- After `data` resolves, if `currentPage > totalPages` (e.g. user edits URL to `?page=999`,
  or filtering shrinks the result set), the API returns an empty `items` array. The empty-state
  block (lines 90-96) already covers "no books found"; clamping `currentPage` in 2.3 keeps the
  Pagination control sane. Optionally `goto` to the last valid page when `items.length === 0 &&
  currentPage > 1` — decide during implementation; not required for correctness.
- **Verify:** navigating to `?page=999` shows the empty state and a usable pagination control,
  no crash.

---

## Phase 3 — (Optional) accept `page` on the API

Only if you prefer the API to speak pages directly. **Default: skip** — `offset`/`limit` already
work and the frontend conversion is trivial.

**File:** `audiblimey/api/routes/library.py`
- Add `page: Optional[int] = Query(None, ge=1)`; when provided, compute
  `offset = (page - 1) * limit` (ignore/override `offset`). Keep `offset` for back-compat.
- Update `tests/test_library_routes.py` to assert `page=2` yields `offset = limit`.
- **Verify:** `python -m pytest tests/test_library_routes.py -v`.

---

## Phase 4 — (Optional) polish

- **Debounce search** (~250ms) before calling `setParams` so each keystroke doesn't push a
  history entry. Use `goto(..., { replaceState: true })` for search-typing to avoid polluting
  Back history; use a normal push for explicit page clicks.
- **Scroll to top** on page change (`noScroll: false` for page nav, already in 2.2).
- **"Showing X–Y of N"** summary line near the grid for orientation.

---

## Files touched (summary)

| File | Change |
|------|--------|
| `src/lib/components/Pagination.svelte` | **new** — numbered pagination with ellipsis |
| `src/routes/library/+page.svelte` | URL-derived state, `setParams`, swap inline Prev/Next for `<Pagination>` |
| `audiblimey/api/routes/library.py` | *optional* (Phase 3) accept `page` param |
| `tests/test_library_routes.py` | *optional* (Phase 3) test page→offset |

## Success criteria

1. User can click a page number and jump directly to it.
2. URL reflects page + filters; refresh, bookmark, share, and Back/Forward all restore state.
3. Changing any filter resets to page 1.
4. `npm run check` passes; existing `tests/` still green (no backend change in the default path).

## Alternatives considered

- **Keep filters in local state, only `page` in URL** — smaller diff, but a shared `?page=3`
  link loses the filters that produced page 3, so it can show a mismatched page. Rejected for
  the "best practices" goal; easy to fall back to if desired.
- **Infinite scroll instead of pages** — contradicts the explicit request to browse to a
  *specific* page. Rejected.
- **Backend `page` param (Phase 3)** — marginal benefit; offset/limit already suffice. Left optional.
