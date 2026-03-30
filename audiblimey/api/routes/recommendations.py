"""Recommendation API routes for audiblimey."""

import logging
from typing import Optional

from fastapi import APIRouter, Query

from audiblimey.db import get_cursor
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

logger = logging.getLogger(__name__)
router = APIRouter(tags=["recommendations"])


@router.get("/recommendations")
async def get_recommendations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    suggestion_type: Optional[str] = Query(None),
):
    """Get scored and explained recommendations.
    
    Returns recommendations ranked by rating-weighted score with full explainability.
    """
    # Pre-compute scoring data
    author_scores = get_author_scores()
    narrator_scores = get_narrator_scores()
    negative_signals = get_negative_signals()
    series_progress_data = get_series_progress()
    
    # Get recommendation candidates from database
    with get_cursor() as cur:
        query = """
            SELECT r.id, r.book_id, b.asin, b.title, b.runtime_length_min,
                   r.suggestion_type, r.source_name, r.confidence_score,
                   bp.member_price, bp.list_price
            FROM user_recommendations r
            JOIN books b ON r.book_id = b.id
            LEFT JOIN LATERAL (
                SELECT member_price, list_price
                FROM book_prices
                WHERE book_id = r.book_id
                ORDER BY price_date DESC
                LIMIT 1
            ) bp ON TRUE
            WHERE r.user_id = 1 AND r.is_dismissed = FALSE
        """
        params = []
        if suggestion_type:
            query += " AND r.suggestion_type = %s"
            params.append(suggestion_type)
        
        query += " ORDER BY r.confidence_score DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
    
    # Score each recommendation
    scored = []
    for row in rows:
        rec_id, book_id, asin, title, runtime, stype, source, old_confidence, member_price, list_price = row
        
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
        
        if rec_score.final_score >= min_score:
            breakdown = generate_score_breakdown(rec_score)
            scored.append({
                "id": rec_id,
                "book": {
                    "asin": asin,
                    "title": title,
                    "runtime_minutes": runtime,
                    "runtime_hours": round(runtime / 60, 1) if runtime else None,
                },
                "score": breakdown["final_score"],
                "old_confidence": float(old_confidence) if old_confidence else None,
                "suggestion_type": stype,
                "source_name": source,
                "explanation": breakdown["explanation"],
                "short_explanation": generate_short_explanation(rec_score),
                "score_breakdown": breakdown["components"],
                "pricing": {
                    "member_price": float(member_price) if member_price else None,
                    "list_price": float(list_price) if list_price else None,
                } if member_price or list_price else None,
            })
    
    # Sort by new score
    scored.sort(key=lambda x: x["score"], reverse=True)
    
    # Paginate
    total = len(scored)
    page = scored[offset:offset + limit]
    
    return {
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/recommendations/series")
async def get_series_recommendations():
    """Get incomplete series with urgency ranking.
    
    Shows series the user has started but not completed,
    ordered by a combination of progress and rating.
    """
    series_list = get_series_progress()
    
    # Enrich with next book info
    enriched = []
    for sp in series_list:
        with get_cursor() as cur:
            # Find the next unowned book in the series
            cur.execute("""
                SELECT b.asin, b.title, b.runtime_length_min, bs.sequence,
                       bp.member_price, bp.list_price
                FROM book_series bs
                JOIN books b ON bs.book_id = b.id
                JOIN series s ON bs.series_id = s.id
                LEFT JOIN user_libraries ul ON b.id = ul.book_id AND ul.user_id = 1
                LEFT JOIN LATERAL (
                    SELECT member_price, list_price
                    FROM book_prices
                    WHERE book_id = b.id
                    ORDER BY price_date DESC
                    LIMIT 1
                ) bp ON TRUE
                WHERE s.title = %s AND ul.id IS NULL
                ORDER BY bs.sequence ASC
                LIMIT 1
            """, (sp["series_title"],))
            next_book = cur.fetchone()
        
        item = {**sp}
        if next_book:
            asin, title, runtime, seq, member_price, list_price = next_book
            item["next_book"] = {
                "asin": asin,
                "title": title,
                "sequence": float(seq) if seq else None,
                "runtime_minutes": runtime,
                "pricing": {
                    "member_price": float(member_price) if member_price else None,
                    "list_price": float(list_price) if list_price else None,
                } if member_price or list_price else None,
            }
        
        enriched.append(item)
    
    return {"series": enriched}


@router.get("/recommendations/{rec_id}")
async def get_recommendation_detail(rec_id: int):
    """Get a single recommendation with full explanation."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT r.id, b.asin, b.title, b.subtitle, b.runtime_length_min,
                   b.merchandising_summary, b.language,
                   r.suggestion_type, r.source_name, r.confidence_score
            FROM user_recommendations r
            JOIN books b ON r.book_id = b.id
            WHERE r.id = %s AND r.user_id = 1
        """, (rec_id,))
        row = cur.fetchone()
    
    if not row:
        from fastapi import HTTPException
        raise HTTPException(404, f"Recommendation {rec_id} not found")
    
    rec_id, asin, title, subtitle, runtime, summary, language, stype, source, old_conf = row
    
    # Score it
    author_scores = get_author_scores()
    narrator_scores = get_narrator_scores()
    negative_signals = get_negative_signals()
    series_progress_data = get_series_progress()
    
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
