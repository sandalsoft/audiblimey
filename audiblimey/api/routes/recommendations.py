"""Recommendation API routes for audiblimey."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from audiblimey.api.covers import resolve_image_url
from audiblimey.db import get_cursor
from audiblimey.sync.audible import _best_image_url, client_from_db, store_book
from audiblimey.sync.catalog import search_catalog
from audiblimey.engine.taste import excluded_book_ids
from audiblimey.engine.scoring import (
    get_author_scores,
    get_narrator_scores,
    get_negative_signals,
    get_series_progress,
    score_recommendation,
)
from audiblimey.engine.explainability import (
    generate_score_breakdown,
    generate_short_explanation,
)
from audiblimey.engine.recommend_chat import (
    DEFAULT_ASK_LIMIT,
    MAX_ASK_LIMIT,
    AskModelError,
    run_ask,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["recommendations"])


def _pick_group_genre(members: list[dict]) -> Optional[dict]:
    """Most frequent genre across a series group's members (stable tie-break)."""
    counts: dict[int, list] = {}
    for m in members:
        genre = m["genre"]
        if not genre:
            continue
        bucket = counts.setdefault(genre["id"], [0, genre])
        bucket[0] += 1
    if not counts:
        return None
    best = sorted(counts.values(), key=lambda cg: (-cg[0], cg[1]["name"] or "", cg[1]["id"]))[0]
    return best[1]


def _gather_candidates(
    suggestion_type: Optional[str] = None, min_score: float = 0.0
) -> list[dict]:
    """Score and filter raw recommendation rows into per-candidate dicts.

    Shared by the recommendation feed (GET) and the LLM ask route (POST). Returns
    the pre-grouping candidate list; each entry carries the data both surfaces
    need (book card, primary series, genre, pricing, cover).
    """
    # Resolve taste-rule exclusions once; reuse for scoring signals + candidate suppression.
    with get_cursor() as cur:
        excluded = excluded_book_ids(cur, 1)

    # Pre-compute scoring data (excluded books do not contribute signals)
    author_scores = get_author_scores(excluded_ids=excluded)
    narrator_scores = get_narrator_scores(excluded_ids=excluded)
    negative_signals = get_negative_signals(excluded_ids=excluded)
    series_progress_data = get_series_progress(excluded_ids=excluded)

    # Get recommendation candidates from database. One query carries pricing,
    # narrators, cover/ISBN fallback, the book's primary series, and primary genre.
    # The NOT EXISTS drops candidates whose primary series is already started.
    with get_cursor() as cur:
        query = """
            SELECT r.id, r.book_id, b.asin, b.title, b.runtime_length_min,
                   r.suggestion_type, r.source_name, r.confidence_score,
                   bp.member_price, bp.list_price,
                   COALESCE(ARRAY(
                       SELECT n.name FROM book_narrators bn
                       JOIN narrators n ON bn.narrator_id = n.id
                       WHERE bn.book_id = r.book_id
                   ), '{}') AS narrators,
                   b.isbn, bed.image_url,
                   (
                       SELECT COALESCE(NULLIF(gb.isbn13, ''), NULLIF(gb.isbn, ''))
                       FROM book_isbn_asin_map biam
                       LEFT JOIN goodreads_books gb ON gb.id = biam.goodreads_book_id
                       WHERE biam.asin = b.asin
                       ORDER BY biam.confidence DESC NULLS LAST, biam.matched_at DESC
                       LIMIT 1
                   ) AS matched_isbn,
                   ps.series_id, ps.series_title, ps.sequence,
                   g.genre_id, g.genre_name
            FROM user_recommendations r
            JOIN books b ON r.book_id = b.id
            LEFT JOIN book_extended_data bed ON bed.book_id = r.book_id
            LEFT JOIN LATERAL (
                SELECT member_price, list_price
                FROM book_prices
                WHERE book_id = r.book_id
                ORDER BY price_date DESC
                LIMIT 1
            ) bp ON TRUE
            LEFT JOIN LATERAL (
                SELECT bs.series_id, s.title AS series_title, bs.sequence
                FROM book_series bs
                JOIN series s ON s.id = bs.series_id
                WHERE bs.book_id = r.book_id
                ORDER BY bs.sequence NULLS LAST, s.title, s.id
                LIMIT 1
            ) ps ON TRUE
            LEFT JOIN LATERAL (
                SELECT c.id AS genre_id, c.name AS genre_name
                FROM book_categories bc
                JOIN categories c ON c.id = bc.category_id
                WHERE bc.book_id = r.book_id
                ORDER BY c.level ASC NULLS LAST, c.name, c.id
                LIMIT 1
            ) g ON TRUE
            WHERE r.user_id = 1 AND r.is_dismissed = FALSE
              AND r.book_id <> ALL(%s::bigint[])
              AND NOT EXISTS (
                  SELECT 1
                  FROM book_series bs2
                  JOIN user_libraries ul2 ON ul2.book_id = bs2.book_id AND ul2.user_id = 1
                  WHERE bs2.series_id = ps.series_id
              )
        """
        params = [list(excluded)]
        if suggestion_type:
            query += " AND r.suggestion_type = %s"
            params.append(suggestion_type)

        query += " ORDER BY r.confidence_score DESC"
        cur.execute(query, params)
        rows = cur.fetchall()

    # Score each surviving candidate
    candidates = []
    for row in rows:
        (rec_id, book_id, asin, title, runtime, stype, source, old_confidence,
         member_price, list_price, narrators, isbn, cached_image, matched_isbn,
         series_id, series_title, series_seq, genre_id, genre_name) = row

        rec_score = score_recommendation(
            book_asin=asin,
            book_title=title,
            suggestion_type=stype,
            source_name=source or "",
            author_scores=author_scores,
            narrator_scores=narrator_scores,
            negative_signals=negative_signals,
            series_progress=series_progress_data,
            book_narrators=narrators,
        )

        if rec_score.final_score < min_score:
            continue

        breakdown = generate_score_breakdown(rec_score)
        image_url = resolve_image_url(cached_image, isbn, matched_isbn)
        genre = {"id": genre_id, "name": genre_name} if genre_id is not None else None
        pricing = {
            "member_price": float(member_price) if member_price else None,
            "list_price": float(list_price) if list_price else None,
        } if member_price or list_price else None

        candidates.append({
            "rec_id": rec_id,
            "book_id": book_id,
            "asin": asin,
            "score": breakdown["final_score"],
            "series_id": series_id,
            "series_title": series_title,
            "series_seq": float(series_seq) if series_seq is not None else None,
            "genre": genre,
            "image_url": image_url,
            "title": title,
            "pricing": pricing,
            "book_item": {
                "type": "book",
                "id": rec_id,
                "book": {
                    "asin": asin,
                    "title": title,
                    "runtime_minutes": runtime,
                    "runtime_hours": round(runtime / 60, 1) if runtime else None,
                    "image_url": image_url,
                },
                "score": breakdown["final_score"],
                "old_confidence": float(old_confidence) if old_confidence else None,
                "suggestion_type": stype,
                "source_name": source,
                "genre": genre,
                "explanation": breakdown["explanation"],
                "short_explanation": generate_short_explanation(rec_score),
                "score_breakdown": breakdown["components"],
                "pricing": pricing,
            },
        })

    return candidates


def _group_feed(candidates: list[dict]) -> list[dict]:
    """Collapse same-series candidates into series cards; keep the rest as books.

    Returns the mixed feed (book + series cards) sorted by score desc, then title.
    """
    # Group candidates that share a (new) series; 2+ members collapse to one card.
    by_series: dict[int, list] = {}
    for c in candidates:
        if c["series_id"] is not None:
            by_series.setdefault(c["series_id"], []).append(c)

    items = []
    grouped_rec_ids = set()
    for series_id, members in by_series.items():
        if len(members) < 2:
            continue
        grouped_rec_ids.update(m["rec_id"] for m in members)
        members_sorted = sorted(
            members,
            key=lambda m: (m["series_seq"] is None, m["series_seq"] or 0.0, m["title"] or ""),
        )
        items.append({
            "type": "series",
            "series_id": series_id,
            "series_title": members_sorted[0]["series_title"],
            "genre": _pick_group_genre(members),
            "recommended_count": len(members),
            "image_url": members_sorted[0]["image_url"],
            "score": max(m["score"] for m in members),
            "books": [
                {"asin": m["book_item"]["book"]["asin"], "title": m["title"], "sequence": m["series_seq"]}
                for m in members_sorted
            ],
        })

    # Remaining (ungrouped) candidates render as single book cards.
    for c in candidates:
        if c["rec_id"] not in grouped_rec_ids:
            items.append(c["book_item"])

    # Sort the mixed list by score desc, then stable title.
    def _sort_key(it):
        title = it["series_title"] if it["type"] == "series" else it["book"]["title"]
        return (-it["score"], title or "")

    items.sort(key=_sort_key)
    return items


@router.get("/recommendations")
async def get_recommendations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    suggestion_type: Optional[str] = Query(None),
):
    """Get scored and explained recommendations.

    Returns book and grouped-series cards ranked by rating-weighted score.
    Candidates whose primary series the user has already started are suppressed
    here (they live in the "Continue Your Series" surface instead); remaining
    candidates that share a new series collapse into a single series card.
    """
    candidates = _gather_candidates(suggestion_type, min_score)
    items = _group_feed(candidates)

    # Paginate after grouping so total reflects visible cards.
    total = len(items)
    page = items[offset:offset + limit]

    return {
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


class AskBody(BaseModel):
    """Request body for the LLM ask route."""

    prompt: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(DEFAULT_ASK_LIMIT, ge=1, le=MAX_ASK_LIMIT)


def _rated_books(limit: int = 200) -> list[dict]:
    """The user's genuinely-rated books (manual > Goodreads > Audible), best-first.

    Excludes the is_finished fallback used elsewhere — only books the user has an
    actual rating for count as taste signal. Scalar subqueries keep one row per
    book despite multiple ISBN→Goodreads matches. The cap bounds prompt size while
    staying generous (a few hundred rated books is only a few thousand tokens).
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM (
                SELECT b.title,
                       (
                           SELECT string_agg(a.name, ', ' ORDER BY ba.display_order)
                           FROM book_authors ba
                           JOIN authors a ON a.id = ba.author_id
                           WHERE ba.book_id = b.id
                       ) AS authors,
                       COALESCE(
                           ul.user_manual_rating,
                           (
                               SELECT gr.my_rating
                               FROM book_isbn_asin_map biam
                               JOIN goodreads_books gr ON gr.id = biam.goodreads_book_id
                               WHERE biam.asin = b.asin AND gr.my_rating > 0
                               ORDER BY biam.confidence DESC NULLS LAST, biam.matched_at DESC
                               LIMIT 1
                           ),
                           ul.user_rating
                       ) AS rating
                FROM user_libraries ul
                JOIN books b ON b.id = ul.book_id
                WHERE ul.user_id = 1
            ) t
            WHERE t.rating > 0
            ORDER BY t.rating DESC, t.title
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [{"title": title, "author": authors or "", "rating": float(rating)} for title, authors, rating in rows]


def _match_catalog(recs: list[dict]) -> dict[str, list[dict]]:
    """Best-effort map of normalized title → catalog rows (asin, cover, owned).

    The model recommends from its own knowledge; this links any recommendation
    that also exists in the catalog so it becomes clickable.
    """
    titles = sorted({r["title"].strip().lower() for r in recs if r["title"].strip()})
    if not titles:
        return {}
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT lower(b.title) AS key, b.asin, b.isbn, bed.image_url,
                   (
                       SELECT string_agg(a.name, ', ' ORDER BY ba.display_order)
                       FROM book_authors ba
                       JOIN authors a ON a.id = ba.author_id
                       WHERE ba.book_id = b.id
                   ) AS authors,
                   EXISTS(
                       SELECT 1 FROM user_libraries ul
                       WHERE ul.book_id = b.id AND ul.user_id = 1
                   ) AS owned
            FROM books b
            LEFT JOIN book_extended_data bed ON bed.book_id = b.id
            WHERE lower(b.title) = ANY(%s::text[])
            """,
            (titles,),
        )
        rows = cur.fetchall()
    by_title: dict[str, list[dict]] = {}
    for key, asin, isbn, image_url, authors, owned in rows:
        by_title.setdefault(key, []).append({
            "asin": asin,
            "image_url": resolve_image_url(image_url, isbn, None),
            "authors": authors or "",
            "owned": bool(owned),
            "href": f"/books/{asin}",
        })
    return by_title


def _best_catalog_match(matches: list[dict], author: str) -> Optional[dict]:
    """Pick the catalog row that best fits a recommendation, preferring author overlap."""
    if not matches:
        return None
    if author:
        wanted = author.lower()
        for m in matches:
            cand = (m["authors"] or "").lower()
            if cand and (cand in wanted or wanted in cand):
                return m
    return matches[0]


def _pick_product(products: list[dict], title: str, author: str) -> Optional[dict]:
    """Pick the Audible product matching a recommended title (exact title only).

    Exact title match avoids linking the wrong book; author disambiguates when
    several products share the title. Returns None when nothing matches confidently.
    """
    target = title.strip().lower()
    if not target:
        return None
    exact = [p for p in products if (p.get("title") or "").strip().lower() == target]
    if not exact:
        return None
    if len(exact) == 1 or not author:
        return exact[0]
    wanted = author.strip().lower()
    for p in exact:
        names = ", ".join((a.get("name") or "") for a in (p.get("authors") or [])).lower()
        if names and (wanted in names or names in wanted):
            return p
    return exact[0]


def _resolve_uncataloged(recs: list[dict], user_id: int = 1) -> dict[str, dict]:
    """Resolve recommended titles to real Audible products → covers + detail pages.

    Each confident match is stored (in_library=False, the catalog-discovery pattern)
    so it gains a /books/{asin} page and cached cover, then keyed by lowercased title.
    Best-effort: missing/expired Audible auth or a failed lookup just leaves that
    recommendation unlinked.
    """
    if not recs:
        return {}
    try:
        client = client_from_db(user_id)
    except Exception as exc:  # noqa: BLE001 — auth missing/expired; degrade gracefully
        logger.info("Audible client unavailable; recommendations left unlinked: %s", exc)
        return {}

    def _search(rec: dict) -> tuple[dict, Optional[dict]]:
        products = search_catalog(
            client, keywords=rec["title"], author=rec["author"] or None, num_results=10
        )
        return rec, _pick_product(products, rec["title"], rec["author"])

    resolved: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for rec, product in pool.map(_search, recs):
            if not product or not product.get("asin"):
                continue
            try:
                with get_cursor() as cur:
                    store_book(cur, user_id, product, in_library=False)
            except Exception as exc:  # noqa: BLE001 — one bad store shouldn't sink the rest
                logger.warning("Failed to store resolved book %s: %s", product.get("asin"), exc)
                continue
            resolved[rec["title"].strip().lower()] = {
                "asin": product["asin"],
                "image_url": _best_image_url(product),
                "href": f"/books/{product['asin']}",
                "owned": False,
            }
    return resolved


@router.post("/recommendations/ask")
async def ask_recommendations(body: AskBody):
    """Recommend audiobooks from an LLM grounded in the user's rated books.

    Context is the user's rated books with ratings (their taste) plus the prompt;
    the model recommends real titles, which we best-effort match back to the catalog
    so owned/available books become clickable. Returns 503 when OPENAI_API_KEY is
    missing/invalid, 502 on a model failure, and 200 with empty items when the user
    has not rated any books yet.
    """
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt must not be empty")

    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured. Cannot ask for recommendations.",
        )

    rated = _rated_books()
    if not rated:
        return {
            "text": (
                "Rate a few books first — I use your ratings to tailor recommendations "
                "to your taste."
            ),
            "items": [],
            "rated_count": 0,
        }

    try:
        text, recs = run_ask(prompt, rated, body.limit)
    except ValueError as exc:
        logger.error("Recommendation ask returned malformed model output: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"The recommendation model returned an unexpected response: {exc}",
        )
    except AskModelError as exc:
        logger.error("Recommendation ask model call failed: %s", exc)
        raise HTTPException(status_code=503 if exc.auth else 502, detail=str(exc))

    # Link recommendations to real objects: catalog first (cheap, owned-aware),
    # then resolve the rest against Audible so they gain covers + detail pages.
    matches = _match_catalog(recs)
    uncataloged = [r for r in recs if r["title"].strip().lower() not in matches]
    resolved = _resolve_uncataloged(uncataloged)

    items = []
    for r in recs:
        key = r["title"].strip().lower()
        info = _best_catalog_match(matches.get(key, []), r["author"]) or resolved.get(key)
        items.append({
            "title": r["title"],
            "author": r["author"],
            "reason": r["reason"],
            "asin": info["asin"] if info else None,
            "image_url": info["image_url"] if info else None,
            "href": info["href"] if info else None,
            "owned": info["owned"] if info else False,
        })
    return {"text": text, "items": items, "rated_count": len(rated)}


@router.get("/recommendations/series")
async def get_series_recommendations():
    """Get incomplete series with urgency ranking.
    
    Shows series the user has started but not completed,
    ordered by a combination of progress and rating.
    """
    with get_cursor() as cur:
        excluded = excluded_book_ids(cur, 1)
    excl = list(excluded)

    series_list = get_series_progress(excluded_ids=excluded)
    series_ids = [sp["series_id"] for sp in series_list]

    # One batched query resolves the next unowned, non-excluded book per series
    # (keyed by series_id, not title), with cover and genre.
    next_by_series: dict[int, dict] = {}
    if series_ids:
        with get_cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (bs.series_id)
                       bs.series_id, b.asin, b.title, b.runtime_length_min, bs.sequence,
                       b.isbn, bed.image_url,
                       (
                           SELECT COALESCE(NULLIF(gb.isbn13, ''), NULLIF(gb.isbn, ''))
                           FROM book_isbn_asin_map biam
                           LEFT JOIN goodreads_books gb ON gb.id = biam.goodreads_book_id
                           WHERE biam.asin = b.asin
                           ORDER BY biam.confidence DESC NULLS LAST, biam.matched_at DESC
                           LIMIT 1
                       ) AS matched_isbn,
                       g.genre_id, g.genre_name,
                       bp.member_price, bp.list_price
                FROM book_series bs
                JOIN books b ON bs.book_id = b.id
                LEFT JOIN book_extended_data bed ON bed.book_id = b.id
                LEFT JOIN user_libraries ul ON b.id = ul.book_id AND ul.user_id = 1
                LEFT JOIN LATERAL (
                    SELECT c.id AS genre_id, c.name AS genre_name
                    FROM book_categories bc
                    JOIN categories c ON c.id = bc.category_id
                    WHERE bc.book_id = b.id
                    ORDER BY c.level ASC NULLS LAST, c.name, c.id
                    LIMIT 1
                ) g ON TRUE
                LEFT JOIN LATERAL (
                    SELECT member_price, list_price
                    FROM book_prices
                    WHERE book_id = b.id
                    ORDER BY price_date DESC
                    LIMIT 1
                ) bp ON TRUE
                WHERE bs.series_id = ANY(%s::bigint[]) AND ul.id IS NULL
                  AND b.id <> ALL(%s::bigint[])
                ORDER BY bs.series_id, bs.sequence ASC NULLS LAST
            """, (series_ids, excl))
            for nb in cur.fetchall():
                (sid, asin, title, runtime, seq, isbn, cached_image, matched_isbn,
                 genre_id, genre_name, member_price, list_price) = nb
                next_by_series[sid] = {
                    "asin": asin,
                    "title": title,
                    "sequence": float(seq) if seq is not None else None,
                    "runtime_minutes": runtime,
                    "image_url": resolve_image_url(cached_image, isbn, matched_isbn),
                    "genre": {"id": genre_id, "name": genre_name} if genre_id is not None else None,
                    "pricing": {
                        "member_price": float(member_price) if member_price else None,
                        "list_price": float(list_price) if list_price else None,
                    } if member_price or list_price else None,
                }

    enriched = []
    for sp in series_list:
        item = {**sp}
        next_book = next_by_series.get(sp["series_id"])
        if next_book:
            item["next_book"] = next_book
        enriched.append(item)

    return {"series": enriched}


@router.get("/recommendations/{rec_id}")
async def get_recommendation_detail(rec_id: int):
    """Get a single recommendation with full explanation."""
    from fastapi import HTTPException

    with get_cursor() as cur:
        cur.execute("""
            SELECT r.id, r.book_id, b.asin, b.title, b.subtitle, b.runtime_length_min,
                   b.merchandising_summary, b.language,
                   r.suggestion_type, r.source_name, r.confidence_score
            FROM user_recommendations r
            JOIN books b ON r.book_id = b.id
            WHERE r.id = %s AND r.user_id = 1
        """, (rec_id,))
        row = cur.fetchone()
        excluded = excluded_book_ids(cur, 1)

    if not row:
        raise HTTPException(404, f"Recommendation {rec_id} not found")

    rec_id, book_id, asin, title, subtitle, runtime, summary, language, stype, source, old_conf = row

    # An excluded title is not a recommendation candidate.
    if book_id in excluded:
        raise HTTPException(404, f"Recommendation {rec_id} not found")

    # Score it (excluded books do not contribute signals)
    author_scores = get_author_scores(excluded_ids=excluded)
    narrator_scores = get_narrator_scores(excluded_ids=excluded)
    negative_signals = get_negative_signals(excluded_ids=excluded)
    series_progress_data = get_series_progress(excluded_ids=excluded)
    
    rec_score = score_recommendation(
        book_asin=asin,
        book_title=title,
        suggestion_type=stype,
        source_name=source or "",
        author_scores=author_scores,
        narrator_scores=narrator_scores,
        negative_signals=negative_signals,
        series_progress=series_progress_data,
    )
    
    breakdown = generate_score_breakdown(rec_score)
    
    # Get authors and narrators
    with get_cursor() as cur:
        cur.execute("""
            SELECT a.name FROM authors a
            JOIN book_authors ba ON a.id = ba.author_id
            JOIN books b ON ba.book_id = b.id
            WHERE b.asin = %s
        """, (asin,))
        authors = [r[0] for r in cur.fetchall()]
        
        cur.execute("""
            SELECT n.name FROM narrators n
            JOIN book_narrators bn ON n.id = bn.narrator_id
            JOIN books b ON bn.book_id = b.id
            WHERE b.asin = %s
        """, (asin,))
        narrators = [r[0] for r in cur.fetchall()]
    
    return {
        "id": rec_id,
        "book": {
            "asin": asin,
            "title": title,
            "subtitle": subtitle,
            "authors": authors,
            "narrators": narrators,
            "runtime_minutes": runtime,
            "runtime_hours": round(runtime / 60, 1) if runtime else None,
            "language": language,
            "summary": summary,
        },
        "score": breakdown["final_score"],
        "old_confidence": float(old_conf) if old_conf else None,
        "suggestion_type": stype,
        "source_name": source,
        "explanation": breakdown["explanation"],
        "short_explanation": generate_short_explanation(rec_score),
        "score_breakdown": breakdown,
    }


@router.post("/recommendations/{rec_id}/dismiss")
async def dismiss_recommendation(rec_id: int):
    """Dismiss a recommendation (won't show again)."""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE user_recommendations SET is_dismissed = TRUE WHERE id = %s AND user_id = 1",
            (rec_id,)
        )
    return {"status": "dismissed", "id": rec_id}
