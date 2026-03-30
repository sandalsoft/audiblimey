"""Embedding and similarity API routes for audiblimey."""

import logging
import os

from fastapi import APIRouter, HTTPException, Path, Query

from audiblimey.db import get_cursor
from audiblimey.engine.embeddings import run_embedding_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(tags=["embeddings"])


@router.get("/books/{asin}/similar")
async def get_similar_books(
    asin: str = Path(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
):
    """Get books similar to the given book by embedding cosine distance.

    Returns up to `limit` similar books ranked by similarity score.
    If the source book has no embedding, returns an empty list (not an error).
    """
    # Look up the source book and its embedding
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, embedding FROM books WHERE asin = %s",
            (asin,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Book with ASIN {asin} not found")

    book_id, embedding = row

    # No embedding yet — return empty rather than error
    if embedding is None:
        return {"items": []}

    # Find similar books by cosine distance, excluding the source book
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT b.asin, b.title,
                   (
                       SELECT COALESCE(string_agg(a.name, ', ' ORDER BY ba.display_order), '')
                       FROM book_authors ba
                       JOIN authors a ON ba.author_id = a.id
                       WHERE ba.book_id = b.id
                   ) AS authors,
                   b.runtime_length_min,
                   1 - (b.embedding <=> %s) AS similarity_score
            FROM books b
            WHERE b.embedding IS NOT NULL AND b.id != %s
            ORDER BY b.embedding <=> %s
            LIMIT %s
            """,
            (str(embedding), book_id, str(embedding), limit),
        )
        rows = cur.fetchall()

    items = []
    for r in rows:
        b_asin, title, authors_str, runtime, sim_score = r
        items.append({
            "asin": b_asin,
            "title": title,
            "authors": authors_str,
            "runtime_hours": round(runtime / 60, 1) if runtime else None,
            "similarity_score": round(float(sim_score), 4) if sim_score is not None else None,
        })

    return {"items": items}


@router.post("/embeddings/generate")
async def generate_embeddings(body: dict | None = None):
    """Trigger the embedding pipeline to process un-embedded books.

    Accepts optional JSON body with { "force": true } to re-embed all books.
    Returns counts of embedded, skipped, and errored books.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured. Cannot generate embeddings.",
        )

    force = bool(body.get("force", False)) if body and isinstance(body, dict) else False

    try:
        stats = run_embedding_pipeline(force=force)
    except Exception as e:
        logger.error("Embedding pipeline failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Embedding pipeline failed: {e}")

    return {
        "embedded": stats["embedded"],
        "skipped": stats["skipped"],
        "errors": stats["errors"],
    }
