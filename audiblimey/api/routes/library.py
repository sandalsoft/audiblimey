"""Library API routes for audiblimey."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query

from audiblimey.db import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["library"])


@router.get("/library")
async def get_library(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(all|finished|in-progress|not-started)$"),
):
    """Get paginated user library with book summaries.

    Returns books in the user's library with authors, narrators,
    listening progress, and total count for pagination.
    """
    user_id = 1

    base_where = "WHERE ul.user_id = %s"
    params: list = [user_id]

    if search:
        base_where += " AND b.title ILIKE %s"
        params.append(f"%{search}%")

    if status and status != "all":
        if status == "finished":
            base_where += " AND ul.is_finished = TRUE"
        elif status == "in-progress":
            base_where += " AND ul.is_finished = FALSE AND ul.percent_complete > 0"
        elif status == "not-started":
            base_where += " AND ul.is_finished = FALSE AND ul.percent_complete = 0"

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

    # Main query with aggregated authors and narrators
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT b.asin, b.title, b.runtime_length_min,
                   ul.percent_complete, ul.is_finished, ul.purchase_date, ul.user_rating,
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
                   ) AS narrators
            FROM user_libraries ul
            JOIN books b ON ul.book_id = b.id
            {base_where}
            ORDER BY ul.purchase_date DESC NULLS LAST
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    items = []
    for row in rows:
        asin, title, runtime, pct, finished, purchase_date, rating, authors_str, narrators_str = row
        items.append({
            "asin": asin,
            "title": title,
            "runtime_minutes": runtime,
            "runtime_hours": round(runtime / 60, 1) if runtime else None,
            "percent_complete": float(pct) if pct is not None else 0.0,
            "is_finished": finished,
            "purchase_date": purchase_date.isoformat() if purchase_date else None,
            "user_rating": float(rating) if rating else None,
            "authors": authors_str,
            "narrators": narrators_str,
        })

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


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
                   b.release_date, b.content_type
            FROM books b
            WHERE b.asin = %s
            """,
            (asin,),
        )
        book_row = cur.fetchone()

    if not book_row:
        raise HTTPException(status_code=404, detail=f"Book with ASIN {asin} not found")

    book_id, asin, title, subtitle, runtime, summary, language, publisher, release_date, content_type = book_row

    # Authors
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.asin, a.name
            FROM authors a
            JOIN book_authors ba ON a.id = ba.author_id
            WHERE ba.book_id = %s
            ORDER BY ba.display_order
            """,
            (book_id,),
        )
        authors = [{"id": r[0], "asin": r[1], "name": r[2]} for r in cur.fetchall()]

    # Narrators
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.asin, n.name
            FROM narrators n
            JOIN book_narrators bn ON n.id = bn.narrator_id
            WHERE bn.book_id = %s
            ORDER BY bn.display_order
            """,
            (book_id,),
        )
        narrators = [{"id": r[0], "asin": r[1], "name": r[2]} for r in cur.fetchall()]

    # Series
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.asin, s.title, bs.sequence
            FROM series s
            JOIN book_series bs ON s.id = bs.series_id
            WHERE bs.book_id = %s
            ORDER BY s.title
            """,
            (book_id,),
        )
        series_list = [
            {"id": r[0], "asin": r[1], "title": r[2], "sequence": float(r[3]) if r[3] else None}
            for r in cur.fetchall()
        ]

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
        "asin": asin,
        "title": title,
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
        "pricing": pricing,
        "user_library": user_library,
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
