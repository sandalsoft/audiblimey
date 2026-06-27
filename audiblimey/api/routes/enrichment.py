"""Audible product-page enrichment API routes."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Path
from fastapi.concurrency import run_in_threadpool

from audiblimey.db import get_cursor
from audiblimey.sync.audible import client_from_db
from audiblimey.sync.enrich import fetch_book_enrichment, store_book_enrichment

logger = logging.getLogger(__name__)
router = APIRouter(tags=["enrichment"])

STALE_AFTER = timedelta(days=30)
# Per-request HTTP timeout for the three Audible calls behind an enrichment fetch.
ENRICH_TIMEOUT = 15


def _json_array(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _is_stale(enriched_at: datetime | None) -> bool:
    enriched_at = _aware(enriched_at)
    if enriched_at is None:
        return True
    return datetime.now(timezone.utc) - enriched_at > STALE_AFTER


def _rating(avg, count) -> dict:
    return {
        "avg": float(avg) if avg is not None else None,
        "count": int(count) if count is not None else None,
    }


def _read_cached_enrichment(asin: str) -> tuple[int, dict] | None:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                b.id,
                b.publisher_summary,
                bed.tags,
                bed.rating_overall,
                bed.rating_overall_count,
                bed.rating_performance,
                bed.rating_performance_count,
                bed.rating_story,
                bed.rating_story_count,
                bed.editorial_reviews,
                bed.customer_reviews,
                bed.audible_related,
                bed.audible_enriched_at,
                (
                    SELECT COALESCE(json_agg(json_build_object(
                        'id', c.id,
                        'name', c.name
                    ) ORDER BY c.name), '[]'::json)
                    FROM book_categories bc
                    JOIN categories c ON c.id = bc.category_id
                    WHERE bc.book_id = b.id
                ) AS categories
            FROM books b
            LEFT JOIN book_extended_data bed ON bed.book_id = b.id
            WHERE b.asin = %s
            """,
            (asin,),
        )
        row = cur.fetchone()

    if not row:
        return None

    (
        book_id,
        full_description,
        tags,
        rating_overall,
        rating_overall_count,
        rating_performance,
        rating_performance_count,
        rating_story,
        rating_story_count,
        editorial_reviews,
        user_reviews,
        related,
        enriched_at,
        categories,
    ) = row

    return book_id, {
        "full_description": full_description,
        "tags": _json_array(tags),
        "categories": _json_array(categories),
        "ratings": {
            "overall": _rating(rating_overall, rating_overall_count),
            "performance": _rating(rating_performance, rating_performance_count),
            "story": _rating(rating_story, rating_story_count),
        },
        "editorial_reviews": _json_array(editorial_reviews),
        "user_reviews": _json_array(user_reviews),
        "related": _json_array(related),
        "enriched_at": _iso(enriched_at),
        "stale": _is_stale(enriched_at),
        "error": None,
    }


def _with_error(payload: dict, error: Exception) -> dict:
    payload = dict(payload)
    payload["error"] = str(error) or "Audible enrichment unavailable"
    return payload


def _fetch_and_store(user_id: int, book_id: int, asin: str) -> None:
    client = client_from_db(user_id, timeout=ENRICH_TIMEOUT)
    data = fetch_book_enrichment(client, asin)
    with get_cursor() as cur:
        store_book_enrichment(cur, user_id, book_id, asin, data)


@router.get("/books/{asin}/details")
async def get_book_enrichment(asin: str = Path(..., min_length=1)):
    """Return cached Audible product-page enrichment, refreshing stale data."""
    user_id = 1
    cached = _read_cached_enrichment(asin)
    if not cached:
        raise HTTPException(status_code=404, detail=f"Book with ASIN {asin} not found")

    book_id, payload = cached
    if not payload["stale"]:
        return payload

    try:
        await run_in_threadpool(_fetch_and_store, user_id, book_id, asin)
    except Exception as exc:
        logger.warning("Audible enrichment refresh failed for %s: %s", asin, exc)
        return _with_error(payload, exc)

    refreshed = _read_cached_enrichment(asin)
    return refreshed[1] if refreshed else payload


@router.post("/books/{asin}/refresh-details")
async def refresh_book_enrichment(asin: str = Path(..., min_length=1)):
    """Force-refresh Audible product-page enrichment."""
    user_id = 1
    cached = _read_cached_enrichment(asin)
    if not cached:
        raise HTTPException(status_code=404, detail=f"Book with ASIN {asin} not found")

    book_id, payload = cached
    try:
        await run_in_threadpool(_fetch_and_store, user_id, book_id, asin)
    except Exception as exc:
        logger.warning("Audible enrichment force-refresh failed for %s: %s", asin, exc)
        return _with_error(payload, exc)

    refreshed = _read_cached_enrichment(asin)
    return refreshed[1] if refreshed else payload
