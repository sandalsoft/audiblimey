"""Natural language search engine using OpenAI embeddings and pgvector cosine distance."""

import logging
from dataclasses import dataclass
from typing import Optional

from audiblimey.engine.embeddings import (
    EMBEDDING_MODEL,
    _call_openai_embeddings,
    _get_openai_client,
)

logger = logging.getLogger(__name__)


@dataclass
class SearchFilters:
    """Optional filters for narrowing search results."""

    min_runtime_hours: Optional[float] = None
    max_runtime_hours: Optional[float] = None
    min_rating: Optional[float] = None


def search_books(
    cursor,
    query: str,
    filters: Optional[SearchFilters] = None,
    limit: int = 20,
    client=None,
) -> list[dict]:
    """Search books by natural language query using embedding similarity.

    Embeds the query text via OpenAI, then runs a pgvector cosine distance
    search against books.embedding. Optional filters narrow by runtime and
    user rating (from user_libraries for user_id=1).

    Args:
        cursor: psycopg2 cursor (caller manages transaction).
        query: Natural language search query.
        filters: Optional SearchFilters for runtime/rating constraints.
        limit: Max results to return (capped at 50).
        client: Optional OpenAI client (for testing). Created from env if None.

    Returns:
        List of dicts with keys: asin, title, authors, runtime_hours,
        similarity_score, user_rating, categories.
    """
    if client is None:
        client = _get_openai_client()

    limit = min(limit, 50)
    if filters is None:
        filters = SearchFilters()

    # Embed the query text
    logger.info("Embedding search query: %r", query[:80])
    embeddings = _call_openai_embeddings(client, [query])
    query_embedding = embeddings[0]
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    # Build the SQL with optional filter clauses
    where_clauses = ["b.embedding IS NOT NULL"]
    params: list = []

    if filters.min_runtime_hours is not None:
        where_clauses.append("b.runtime_length_min >= %s")
        params.append(int(filters.min_runtime_hours * 60))

    if filters.max_runtime_hours is not None:
        where_clauses.append("b.runtime_length_min <= %s")
        params.append(int(filters.max_runtime_hours * 60))

    if filters.min_rating is not None:
        where_clauses.append("ul.user_rating >= %s")
        params.append(filters.min_rating)

    where_sql = " AND ".join(where_clauses)

    # Join user_libraries for rating filter and to surface user_rating in results.
    # LEFT JOIN so books without a library entry still appear (unless min_rating filters them out).
    join_clause = "LEFT JOIN user_libraries ul ON b.id = ul.book_id AND ul.user_id = 1"

    sql = f"""
        SELECT
            b.asin,
            b.title,
            (
                SELECT COALESCE(string_agg(a.name, ', ' ORDER BY ba.display_order), '')
                FROM book_authors ba
                JOIN authors a ON ba.author_id = a.id
                WHERE ba.book_id = b.id
            ) AS authors,
            b.runtime_length_min,
            1 - (b.embedding <=> %s) AS similarity_score,
            ul.user_rating,
            (
                SELECT COALESCE(string_agg(c.name, ', ' ORDER BY c.name), '')
                FROM book_categories bc
                JOIN categories c ON bc.category_id = c.id
                WHERE bc.book_id = b.id
            ) AS categories
        FROM books b
        {join_clause}
        WHERE {where_sql}
        ORDER BY b.embedding <=> %s
        LIMIT %s
    """

    # params order: embedding for similarity calc, filter params are in where_clauses,
    # then embedding for ORDER BY, then limit
    full_params = [embedding_str] + params + [embedding_str, limit]

    cursor.execute(sql, full_params)
    rows = cursor.fetchall()

    results = []
    for row in rows:
        asin, title, authors, runtime_min, sim_score, user_rating, categories = row
        results.append({
            "asin": asin,
            "title": title,
            "authors": authors,
            "runtime_hours": round(runtime_min / 60, 1) if runtime_min else None,
            "similarity_score": round(float(sim_score), 4) if sim_score is not None else None,
            "user_rating": float(user_rating) if user_rating is not None else None,
            "categories": categories,
        })

    logger.info("Search for %r returned %d results", query[:80], len(results))
    return results
