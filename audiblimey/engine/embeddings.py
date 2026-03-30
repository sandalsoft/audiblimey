"""Embedding engine for book similarity search using OpenAI text-embedding-3-small and pgvector."""

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536
BATCH_SIZE = 50
MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0  # seconds, doubles each retry


def compose_embedding_text(book_row: dict) -> str:
    """Build rich text from book metadata for embedding.

    Handles sparse metadata gracefully — missing fields are simply omitted.
    The dict should contain keys: title, subtitle, authors, categories, summary.
    All values may be None or empty strings.
    """
    parts = []

    title = (book_row.get("title") or "").strip()
    if title:
        parts.append(title)

    subtitle = (book_row.get("subtitle") or "").strip()
    if subtitle:
        parts.append(subtitle)

    authors = (book_row.get("authors") or "").strip()
    if authors:
        parts.append(f"by {authors}")

    categories = (book_row.get("categories") or "").strip()
    if categories:
        parts.append(f"Categories: {categories}")

    summary = (book_row.get("summary") or "").strip()
    if summary:
        parts.append(summary)

    return ". ".join(parts)


def _get_openai_client():
    """Create OpenAI client, raising a clear error if the key is missing."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it before running the embedding pipeline."
        )
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _fetch_books_for_embedding(cursor, force: bool = False) -> list[dict]:
    """Fetch books that need embeddings, with authors and categories via JOINs.

    Returns list of dicts with keys: id, asin, title, subtitle, authors, categories, summary.
    """
    where_clause = "" if force else "WHERE b.embedding IS NULL"

    cursor.execute(f"""
        SELECT
            b.id,
            b.asin,
            b.title,
            b.subtitle,
            b.publisher_summary,
            COALESCE(
                STRING_AGG(DISTINCT a.name, ', ') FILTER (WHERE a.name IS NOT NULL),
                ''
            ) AS authors,
            COALESCE(
                STRING_AGG(DISTINCT c.name, ', ') FILTER (WHERE c.name IS NOT NULL),
                ''
            ) AS categories
        FROM books b
        LEFT JOIN book_authors ba ON ba.book_id = b.id
        LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN book_categories bc ON bc.book_id = b.id
        LEFT JOIN categories c ON c.id = bc.category_id
        {where_clause}
        GROUP BY b.id, b.asin, b.title, b.subtitle, b.publisher_summary
        ORDER BY b.id
    """)

    rows = cursor.fetchall()
    books = []
    for row in rows:
        books.append({
            "id": row[0],
            "asin": row[1],
            "title": row[2],
            "subtitle": row[3],
            "summary": row[4],
            "authors": row[5],
            "categories": row[6],
        })
    return books


def _call_openai_embeddings(client, texts: list[str]) -> list[list[float]]:
    """Call OpenAI embeddings API with exponential backoff retry.

    Returns list of embedding vectors in the same order as input texts.
    """
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=texts,
            )
            # Response data is ordered by index
            sorted_data = sorted(response.data, key=lambda d: d.index)
            return [item.embedding for item in sorted_data]
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "OpenAI API call failed (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt + 1, MAX_RETRIES, e, delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "OpenAI API call failed after %d attempts: %s",
                    MAX_RETRIES, e,
                )
    raise last_error


def _store_embedding(cursor, book_id: int, embedding: list[float]):
    """Store embedding vector in pgvector column using string format."""
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    cursor.execute(
        "UPDATE books SET embedding = %s WHERE id = %s",
        (embedding_str, book_id),
    )


def embed_books(cursor, force: bool = False, client=None) -> dict:
    """Select un-embedded books (or all if force) and generate embeddings.

    Args:
        cursor: psycopg2 cursor (caller manages transaction).
        force: If True, re-embed all books regardless of existing embedding.
        client: Optional OpenAI client (for testing). Created from env if None.

    Returns:
        dict with keys: embedded, skipped, errors, error_details.
    """
    if client is None:
        client = _get_openai_client()

    books = _fetch_books_for_embedding(cursor, force=force)
    total = len(books)

    if total == 0:
        logger.info("No books to embed.")
        return {"embedded": 0, "skipped": 0, "errors": 0, "error_details": []}

    logger.info("Found %d books to embed (force=%s)", total, force)

    embedded = 0
    errors = 0
    error_details = []

    # Process in batches
    for batch_start in range(0, total, BATCH_SIZE):
        batch = books[batch_start : batch_start + BATCH_SIZE]
        texts = [compose_embedding_text(b) for b in batch]

        # Skip books with no meaningful text
        valid_indices = [i for i, t in enumerate(texts) if t.strip()]
        if not valid_indices:
            logger.warning(
                "Batch starting at %d has no valid texts, skipping", batch_start
            )
            continue

        valid_texts = [texts[i] for i in valid_indices]
        valid_books = [batch[i] for i in valid_indices]

        try:
            embeddings = _call_openai_embeddings(client, valid_texts)

            for book, emb in zip(valid_books, embeddings):
                _store_embedding(cursor, book["id"], emb)
                embedded += 1

            logger.info(
                "Batch %d-%d: embedded %d/%d books",
                batch_start,
                batch_start + len(batch),
                len(valid_books),
                len(batch),
            )
        except Exception as e:
            errors += len(valid_books)
            error_details.append({
                "batch_start": batch_start,
                "batch_size": len(batch),
                "error": str(e),
            })
            logger.error(
                "Batch %d-%d failed: %s", batch_start, batch_start + len(batch), e
            )

    skipped = total - embedded - errors
    return {
        "embedded": embedded,
        "skipped": skipped,
        "errors": errors,
        "error_details": error_details,
    }


def run_embedding_pipeline(force: bool = False) -> dict:
    """Top-level orchestrator: opens DB cursor, runs embedding, logs summary.

    Returns:
        dict with keys: embedded, skipped, errors, error_details.
    """
    from audiblimey.db import get_cursor

    logger.info("Starting embedding pipeline (force=%s)", force)
    start_time = time.time()

    with get_cursor() as cursor:
        stats = embed_books(cursor, force=force)

    elapsed = time.time() - start_time
    logger.info(
        "Embedding pipeline complete in %.1fs: %d embedded, %d skipped, %d errors",
        elapsed,
        stats["embedded"],
        stats["skipped"],
        stats["errors"],
    )

    if stats["error_details"]:
        logger.warning("Error details:")
        for detail in stats["error_details"]:
            logger.warning(
                "  Batch at offset %d (%d books): %s",
                detail["batch_start"],
                detail["batch_size"],
                detail["error"],
            )

    return stats
