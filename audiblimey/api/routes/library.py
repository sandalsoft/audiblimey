"""Library API routes for audiblimey."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from audiblimey.api.covers import resolve_image_url
from audiblimey.db import get_cursor
from audiblimey.engine.taste import excluded_book_ids

logger = logging.getLogger(__name__)
router = APIRouter(tags=["library"])


class RatingBody(BaseModel):
    """Request body for setting a personal rating (1–5 stars, or null to clear)."""

    rating: int | None


# Per-book "card" columns shared by the library list and series endpoints.
# Yields 19 columns (b.id … title_rule) consumed by _row_to_book_item.
# Requires b (books), ul (user_libraries), bed (book_extended_data) in scope.
# taste_rules subqueries inline user_id=1 (single-user) to avoid param threading.
_BOOK_CARD_COLUMNS = """
    b.id, b.asin, b.title, b.runtime_length_min,
    ul.percent_complete, ul.is_finished, ul.purchase_date, ul.user_rating,
    ul.user_manual_rating, b.isbn, bed.image_url,
    (
        SELECT COALESCE(NULLIF(gb.isbn13, ''), NULLIF(gb.isbn, ''))
        FROM book_isbn_asin_map biam
        LEFT JOIN goodreads_books gb ON gb.id = biam.goodreads_book_id
        WHERE biam.asin = b.asin
        ORDER BY biam.confidence DESC NULLS LAST, biam.matched_at DESC
        LIMIT 1
    ) AS matched_isbn,
    (
        SELECT COALESCE(string_agg(a.name, ', ' ORDER BY ba.display_order), '')
        FROM book_authors ba
        JOIN authors a ON ba.author_id = a.id
        WHERE ba.book_id = b.id
    ) AS authors,
    (
        SELECT COALESCE(string_agg(n.name, ', ' ORDER BY bn.display_order), '')
        FROM book_narrators bn
        JOIN narrators n ON bn.narrator_id = n.id
        WHERE bn.book_id = b.id
    ) AS narrators,
    (
        SELECT COALESCE(json_agg(json_build_object(
            'id', a.id, 'name', a.name,
            'rule', CASE WHEN tr.id IS NOT NULL THEN json_build_object('id', tr.id, 'mode', tr.mode) END
        ) ORDER BY ba.display_order), '[]'::json)
        FROM book_authors ba
        JOIN authors a ON a.id = ba.author_id
        LEFT JOIN taste_rules tr ON tr.user_id = 1 AND tr.scope = 'author' AND tr.entity_id = a.id
        WHERE ba.book_id = b.id
    ) AS authors_ref,
    (
        SELECT COALESCE(json_agg(json_build_object(
            'id', n.id, 'name', n.name,
            'rule', CASE WHEN tr.id IS NOT NULL THEN json_build_object('id', tr.id, 'mode', tr.mode) END
        ) ORDER BY bn.display_order), '[]'::json)
        FROM book_narrators bn
        JOIN narrators n ON n.id = bn.narrator_id
        LEFT JOIN taste_rules tr ON tr.user_id = 1 AND tr.scope = 'narrator' AND tr.entity_id = n.id
        WHERE bn.book_id = b.id
    ) AS narrators_ref,
    (
        SELECT COALESCE(json_agg(json_build_object(
            'id', c.id, 'name', c.name,
            'rule', CASE WHEN tr.id IS NOT NULL THEN json_build_object('id', tr.id, 'mode', tr.mode) END
        ) ORDER BY c.name), '[]'::json)
        FROM book_categories bc
        JOIN categories c ON c.id = bc.category_id
        LEFT JOIN taste_rules tr ON tr.user_id = 1 AND tr.scope = 'category' AND tr.entity_id = c.id
        WHERE bc.book_id = b.id
    ) AS categories,
    (
        SELECT COALESCE(json_agg(json_build_object(
            'id', s.id, 'name', s.title,
            'rule', CASE WHEN tr.id IS NOT NULL THEN json_build_object('id', tr.id, 'mode', tr.mode) END
        ) ORDER BY bs.sequence), '[]'::json)
        FROM book_series bs
        JOIN series s ON s.id = bs.series_id
        LEFT JOIN taste_rules tr ON tr.user_id = 1 AND tr.scope = 'series' AND tr.entity_id = s.id
        WHERE bs.book_id = b.id
    ) AS series_ref,
    (
        SELECT json_build_object('id', tr.id, 'mode', tr.mode)
        FROM taste_rules tr
        WHERE tr.user_id = 1 AND tr.scope = 'title' AND tr.entity_id = b.id
    ) AS title_rule
"""


def _row_to_book_item(row, excluded) -> dict:
    """Build a library "card" item dict from the first 19 _BOOK_CARD_COLUMNS."""
    (book_id, asin, title, runtime, pct, finished, purchase_date, rating,
     manual_rating, isbn, cached_image_url, matched_isbn, authors_str, narrators_str,
     authors_ref, narrators_ref, categories, series_ref, title_rule) = row[:19]
    return {
        "book_id": book_id,
        "asin": asin,
        "title": title,
        "image_url": resolve_image_url(cached_image_url, isbn, matched_isbn),
        "runtime_minutes": runtime,
        "runtime_hours": round(runtime / 60, 1) if runtime else None,
        "percent_complete": float(pct) if pct is not None else 0.0,
        "is_finished": finished,
        "purchase_date": purchase_date.isoformat() if purchase_date else None,
        "user_rating": float(rating) if rating else None,
        "user_manual_rating": float(manual_rating) if manual_rating is not None else None,
        "taste_excluded": book_id in excluded,
        "authors": authors_str,
        "narrators": narrators_str,
        "authors_ref": authors_ref,
        "narrators_ref": narrators_ref,
        "categories": categories,
        "series": series_ref,
        "title_rule": title_rule,
    }


@router.get("/library")
async def get_library(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(all|finished|in-progress|not-started)$"),
    taste: Optional[str] = Query(None, pattern="^(all|included|excluded)$"),
):
    """Get paginated user library with book summaries.

    Returns books in the user's library with authors, narrators, listening
    progress, taste-rule state (per-title and per-entity), and total count.
    """
    user_id = 1

    with get_cursor() as cur:
        excluded = excluded_book_ids(cur, user_id)
    excl = list(excluded)

    base_where = "WHERE ul.user_id = %s"
    params: list = [user_id]

    if search:
        base_where += """
            AND (
                b.title ILIKE %s
                OR EXISTS (
                    SELECT 1 FROM book_authors ba
                    JOIN authors a ON ba.author_id = a.id
                    WHERE ba.book_id = b.id AND a.name ILIKE %s
                )
                OR EXISTS (
                    SELECT 1 FROM book_narrators bn
                    JOIN narrators n ON bn.narrator_id = n.id
                    WHERE bn.book_id = b.id AND n.name ILIKE %s
                )
            )"""
        like_param = f"%{search}%"
        params.extend([like_param, like_param, like_param])

    if status and status != "all":
        if status == "finished":
            base_where += " AND ul.is_finished = TRUE"
        elif status == "in-progress":
            base_where += " AND ul.is_finished = FALSE AND ul.percent_complete > 0"
        elif status == "not-started":
            base_where += " AND ul.is_finished = FALSE AND ul.percent_complete = 0"

    if taste == "included":
        base_where += " AND ul.book_id <> ALL(%s::bigint[])"
        params.append(excl)
    elif taste == "excluded":
        base_where += " AND ul.book_id = ANY(%s::bigint[])"
        params.append(excl)

    # Count query
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM user_libraries ul
            JOIN books b ON ul.book_id = b.id
            {base_where}
            """,
            params,
        )
        (total,) = cur.fetchone()

    # Main query: display strings + per-entity refs carrying their taste rule (id+mode).
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {_BOOK_CARD_COLUMNS}
            FROM user_libraries ul
            JOIN books b ON ul.book_id = b.id
            LEFT JOIN book_extended_data bed ON bed.book_id = b.id
            {base_where}
            ORDER BY ul.purchase_date DESC NULLS LAST
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    items = [_row_to_book_item(row, excluded) for row in rows]

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.put("/library/{asin}/rating")
async def set_rating(body: RatingBody, asin: str = Path(..., min_length=1)):
    """Set or clear the personal rating for a library title.

    Accepts an integer 1–5, or null to clear. Writes user_manual_rating
    (distinct from the Audible average in user_rating). 404 if the ASIN
    is not in the user's library.
    """
    user_id = 1

    if body.rating is not None and not (1 <= body.rating <= 5):
        raise HTTPException(status_code=422, detail="rating must be an integer 1–5 or null")

    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE user_libraries ul
            SET user_manual_rating = %s
            FROM books b
            WHERE ul.book_id = b.id AND b.asin = %s AND ul.user_id = %s
            RETURNING ul.user_manual_rating
            """,
            (body.rating, asin, user_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"No library entry for ASIN {asin}")

    return {"asin": asin, "user_manual_rating": float(row[0]) if row[0] is not None else None}


@router.get("/books/{asin}")
async def get_book_detail(asin: str = Path(..., min_length=1)):
    """Get full book detail by ASIN.

    Returns book metadata, authors, narrators, series info,
    latest price, and user library entry if present.
    """
    user_id = 1

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT b.id, b.asin, b.title, b.subtitle, b.runtime_length_min,
                   b.merchandising_summary, b.language, b.publisher_name,
                   b.release_date, b.content_type, b.isbn, bed.image_url,
                   (
                       SELECT COALESCE(NULLIF(gb.isbn13, ''), NULLIF(gb.isbn, ''))
                       FROM book_isbn_asin_map biam
                       LEFT JOIN goodreads_books gb ON gb.id = biam.goodreads_book_id
                       WHERE biam.asin = b.asin
                       ORDER BY biam.confidence DESC NULLS LAST, biam.matched_at DESC
                       LIMIT 1
                   ) AS matched_isbn
            FROM books b
            LEFT JOIN book_extended_data bed ON bed.book_id = b.id
            WHERE b.asin = %s
            """,
            (asin,),
        )
        book_row = cur.fetchone()

    if not book_row:
        raise HTTPException(status_code=404, detail=f"Book with ASIN {asin} not found")

    (
        book_id, asin, title, subtitle, runtime, summary, language, publisher,
        release_date, content_type, isbn, cached_image_url, matched_isbn
    ) = book_row

    def _rule(rule_id, rule_mode):
        return {"id": rule_id, "mode": rule_mode} if rule_id is not None else None

    # Authors (with taste rule)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.asin, a.name, tr.id, tr.mode
            FROM authors a
            JOIN book_authors ba ON a.id = ba.author_id
            LEFT JOIN taste_rules tr ON tr.user_id = %s AND tr.scope = 'author' AND tr.entity_id = a.id
            WHERE ba.book_id = %s
            ORDER BY ba.display_order
            """,
            (user_id, book_id),
        )
        authors = [
            {"id": r[0], "asin": r[1], "name": r[2], "rule": _rule(r[3], r[4])}
            for r in cur.fetchall()
        ]

    # Narrators (with taste rule)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.asin, n.name, tr.id, tr.mode
            FROM narrators n
            JOIN book_narrators bn ON n.id = bn.narrator_id
            LEFT JOIN taste_rules tr ON tr.user_id = %s AND tr.scope = 'narrator' AND tr.entity_id = n.id
            WHERE bn.book_id = %s
            ORDER BY bn.display_order
            """,
            (user_id, book_id),
        )
        narrators = [
            {"id": r[0], "asin": r[1], "name": r[2], "rule": _rule(r[3], r[4])}
            for r in cur.fetchall()
        ]

    # Series (with taste rule)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.asin, s.title, bs.sequence, tr.id, tr.mode
            FROM series s
            JOIN book_series bs ON s.id = bs.series_id
            LEFT JOIN taste_rules tr ON tr.user_id = %s AND tr.scope = 'series' AND tr.entity_id = s.id
            WHERE bs.book_id = %s
            ORDER BY s.title
            """,
            (user_id, book_id),
        )
        series_list = [
            {"id": r[0], "asin": r[1], "title": r[2],
             "sequence": float(r[3]) if r[3] else None, "rule": _rule(r[4], r[5])}
            for r in cur.fetchall()
        ]

    # Categories / genres (with taste rule)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.name, tr.id, tr.mode
            FROM categories c
            JOIN book_categories bc ON c.id = bc.category_id
            LEFT JOIN taste_rules tr ON tr.user_id = %s AND tr.scope = 'category' AND tr.entity_id = c.id
            WHERE bc.book_id = %s
            ORDER BY c.name
            """,
            (user_id, book_id),
        )
        categories = [
            {"id": r[0], "name": r[1], "rule": _rule(r[2], r[3])}
            for r in cur.fetchall()
        ]

    # Title-level taste state for this book
    with get_cursor() as cur:
        excluded = excluded_book_ids(cur, user_id)
        cur.execute(
            "SELECT id, mode FROM taste_rules WHERE user_id = %s AND scope = 'title' AND entity_id = %s",
            (user_id, book_id),
        )
        tr_row = cur.fetchone()
    title_rule = _rule(tr_row[0], tr_row[1]) if tr_row else None
    taste_excluded = book_id in excluded

    # Latest price
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT member_price, list_price, credit_price, currency_code, price_date
            FROM book_prices
            WHERE book_id = %s
            ORDER BY price_date DESC
            LIMIT 1
            """,
            (book_id,),
        )
        price_row = cur.fetchone()

    pricing = None
    if price_row:
        member_price, list_price, credit_price, currency, price_date = price_row
        pricing = {
            "member_price": float(member_price) if member_price else None,
            "list_price": float(list_price) if list_price else None,
            "credit_price": float(credit_price) if credit_price else None,
            "currency": currency,
            "price_date": price_date.isoformat() if price_date else None,
        }

    # User library entry
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT percent_complete, is_finished, purchase_date, user_rating
            FROM user_libraries
            WHERE book_id = %s AND user_id = %s
            """,
            (book_id, user_id),
        )
        lib_row = cur.fetchone()

    user_library = None
    if lib_row:
        pct, finished, purchase_date, rating = lib_row
        user_library = {
            "percent_complete": float(pct) if pct is not None else 0.0,
            "is_finished": finished,
            "purchase_date": purchase_date.isoformat() if purchase_date else None,
            "user_rating": float(rating) if rating else None,
        }

    return {
        "book_id": book_id,
        "asin": asin,
        "title": title,
        "image_url": resolve_image_url(cached_image_url, isbn, matched_isbn),
        "subtitle": subtitle,
        "runtime_minutes": runtime,
        "runtime_hours": round(runtime / 60, 1) if runtime else None,
        "summary": summary,
        "language": language,
        "publisher": publisher,
        "release_date": release_date.isoformat() if release_date else None,
        "content_type": content_type,
        "authors": authors,
        "narrators": narrators,
        "series": series_list,
        "categories": categories,
        "title_rule": title_rule,
        "taste_excluded": taste_excluded,
        "pricing": pricing,
        "user_library": user_library,
    }


@router.get("/series/{series_id}")
async def get_series_detail(series_id: int = Path(..., ge=1)):
    """Get a series with all its books (owned or not) and per-book taste state.

    Returns series info, the series-scoped taste rule (if any), and every book
    in the series ordered by sequence — each carrying the same fields a library
    card needs (rating, taste rule, per-entity refs) plus `sequence` and
    `in_library`. Powers the series page's per-book and mass rate/exclude actions.
    """
    user_id = 1

    with get_cursor() as cur:
        cur.execute("SELECT id, asin, title FROM series WHERE id = %s", (series_id,))
        series_row = cur.fetchone()

    if not series_row:
        raise HTTPException(status_code=404, detail=f"Series with ID {series_id} not found")

    sid, series_asin, series_title = series_row

    with get_cursor() as cur:
        excluded = excluded_book_ids(cur, user_id)

        cur.execute(
            "SELECT id, mode FROM taste_rules WHERE user_id = %s AND scope = 'series' AND entity_id = %s",
            (user_id, sid),
        )
        rule_row = cur.fetchone()
    series_rule = {"id": rule_row[0], "mode": rule_row[1]} if rule_row else None

    # Reuse the shared library "card" columns, but anchor on the series and
    # include books the user does not own (LEFT JOIN user_libraries). The outer
    # book_series alias is `sbs` to avoid colliding with `bs` inside the columns.
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {_BOOK_CARD_COLUMNS},
                   sbs.sequence, (ul.id IS NOT NULL) AS in_library
            FROM book_series sbs
            JOIN books b ON sbs.book_id = b.id
            LEFT JOIN user_libraries ul ON ul.book_id = b.id AND ul.user_id = %s
            LEFT JOIN book_extended_data bed ON bed.book_id = b.id
            WHERE sbs.series_id = %s
            ORDER BY sbs.sequence ASC NULLS LAST
            """,
            (user_id, sid),
        )
        rows = cur.fetchall()

    books = []
    owned_count = 0
    ratings = []
    for row in rows:
        item = _row_to_book_item(row, excluded)
        sequence, in_library = row[19], row[20]
        item["sequence"] = float(sequence) if sequence is not None else None
        item["in_library"] = bool(in_library)
        if in_library:
            owned_count += 1
            effective = item["user_manual_rating"]
            if effective is None:
                effective = item["user_rating"]
            if effective is not None:
                ratings.append(effective)
        books.append(item)

    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

    return {
        "id": sid,
        "asin": series_asin,
        "title": series_title,
        "rule": series_rule,
        "book_count": len(books),
        "owned_count": owned_count,
        "avg_rating": avg_rating,
        "books": books,
    }


@router.get("/authors/{author_id}")
async def get_author_profile(author_id: int = Path(..., ge=1)):
    """Get author profile with library stats.

    Returns author info and aggregated stats from
    the user's library (book count, avg rating, total runtime).
    """
    user_id = 1

    with get_cursor() as cur:
        cur.execute(
            "SELECT id, asin, name FROM authors WHERE id = %s",
            (author_id,),
        )
        author_row = cur.fetchone()

    if not author_row:
        raise HTTPException(status_code=404, detail=f"Author with ID {author_id} not found")

    aid, author_asin, name = author_row

    # Books in user's library by this author, plus aggregate stats
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT b.asin, b.title, b.runtime_length_min,
                   ul.percent_complete, ul.is_finished, ul.user_rating
            FROM books b
            JOIN book_authors ba ON b.id = ba.book_id
            JOIN user_libraries ul ON b.id = ul.book_id AND ul.user_id = %s
            WHERE ba.author_id = %s
            ORDER BY ul.purchase_date DESC NULLS LAST
            """,
            (user_id, aid),
        )
        book_rows = cur.fetchall()

    books = []
    total_runtime = 0
    ratings = []
    for row in book_rows:
        b_asin, b_title, b_runtime, pct, finished, rating = row
        books.append({
            "asin": b_asin,
            "title": b_title,
            "runtime_minutes": b_runtime,
            "percent_complete": float(pct) if pct is not None else 0.0,
            "is_finished": finished,
            "user_rating": float(rating) if rating else None,
        })
        if b_runtime:
            total_runtime += b_runtime
        if rating:
            ratings.append(float(rating))

    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

    return {
        "id": aid,
        "asin": author_asin,
        "name": name,
        "stats": {
            "book_count": len(books),
            "avg_rating": avg_rating,
            "total_runtime_minutes": total_runtime,
            "total_runtime_hours": round(total_runtime / 60, 1) if total_runtime else 0,
        },
        "books": books,
    }


@router.get("/narrators/{narrator_id}")
async def get_narrator_profile(narrator_id: int = Path(..., ge=1)):
    """Get narrator profile with library stats.

    Returns narrator info and aggregated stats from
    the user's library (book count, avg rating, total runtime).
    """
    user_id = 1

    with get_cursor() as cur:
        cur.execute(
            "SELECT id, asin, name FROM narrators WHERE id = %s",
            (narrator_id,),
        )
        narrator_row = cur.fetchone()

    if not narrator_row:
        raise HTTPException(status_code=404, detail=f"Narrator with ID {narrator_id} not found")

    nid, narrator_asin, name = narrator_row

    # Books in user's library by this narrator, plus aggregate stats
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT b.asin, b.title, b.runtime_length_min,
                   ul.percent_complete, ul.is_finished, ul.user_rating
            FROM books b
            JOIN book_narrators bn ON b.id = bn.book_id
            JOIN user_libraries ul ON b.id = ul.book_id AND ul.user_id = %s
            WHERE bn.narrator_id = %s
            ORDER BY ul.purchase_date DESC NULLS LAST
            """,
            (user_id, nid),
        )
        book_rows = cur.fetchall()

    books = []
    total_runtime = 0
    ratings = []
    for row in book_rows:
        b_asin, b_title, b_runtime, pct, finished, rating = row
        books.append({
            "asin": b_asin,
            "title": b_title,
            "runtime_minutes": b_runtime,
            "percent_complete": float(pct) if pct is not None else 0.0,
            "is_finished": finished,
            "user_rating": float(rating) if rating else None,
        })
        if b_runtime:
            total_runtime += b_runtime
        if rating:
            ratings.append(float(rating))

    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

    return {
        "id": nid,
        "asin": narrator_asin,
        "name": name,
        "stats": {
            "book_count": len(books),
            "avg_rating": avg_rating,
            "total_runtime_minutes": total_runtime,
            "total_runtime_hours": round(total_runtime / 60, 1) if total_runtime else 0,
        },
        "books": books,
    }
