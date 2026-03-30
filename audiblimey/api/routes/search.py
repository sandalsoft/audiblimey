"""Search API routes for natural language book search."""

import logging
import os

from fastapi import APIRouter, HTTPException, Query

from audiblimey.db import get_cursor
from audiblimey.engine.search import SearchFilters, search_books

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Natural language search query"),
    min_runtime: float | None = Query(None, ge=0, description="Minimum runtime in hours"),
    max_runtime: float | None = Query(None, ge=0, description="Maximum runtime in hours"),
    min_rating: float | None = Query(None, ge=1, le=5, description="Minimum user rating (1-5)"),
    limit: int = Query(20, ge=1, le=50, description="Max results to return"),
):
    """Search books by natural language query with optional filters.

    Uses OpenAI embeddings + pgvector cosine distance for semantic search.
    Returns ranked results with similarity scores.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured. Cannot perform search.",
        )

    filters = SearchFilters(
        min_runtime_hours=min_runtime,
        max_runtime_hours=max_runtime,
        min_rating=min_rating,
    )

    try:
        with get_cursor() as cur:
            results = search_books(cur, query=q, filters=filters, limit=limit)
    except Exception as e:
        logger.error("Search failed for query %r: %s", q, e)
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")

    return {"items": results, "query": q}
