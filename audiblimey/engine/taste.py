"""Taste engine: compute taste vectors and generate LLM taste profiles.

A taste vector is the rating-weighted centroid of a user's book embeddings.
The LLM profile is a natural-language summary of reading preferences, built
from the user's top-rated books, genre distribution, and listening stats.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

EMBEDDING_DIMS = 1536
PROFILE_MODEL = "gpt-4o-mini"
PROFILE_MAX_TOKENS = 600


def _get_openai_client():
    """Create OpenAI client, raising a clear error if the key is missing."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it before generating taste profiles."
        )
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _parse_pgvector(embedding_str: str) -> Optional[list[float]]:
    """Parse pgvector string '[0.1,0.2,...]' into a list of floats.

    Returns None if parsing fails (malformed data).
    """
    if not embedding_str:
        return None
    try:
        cleaned = embedding_str.strip().strip("[]")
        return [float(x) for x in cleaned.split(",")]
    except (ValueError, AttributeError):
        logger.warning("Failed to parse embedding string: %.60s...", embedding_str)
        return None


def compute_taste_vector(
    cursor, user_id: int
) -> tuple[Optional[list[float]], int]:
    """Compute a rating-weighted centroid of the user's book embeddings.

    Rating priority: goodreads my_rating > audible user_rating > is_finished fallback.
    For is_finished fallback: finished=3.5, >50% complete=3.0, else skip.

    Returns:
        (vector, books_count) or (None, 0) if no eligible books.
    """
    # Fetch books with embeddings, join through to goodreads ratings via bridge table.
    # LEFT JOINs let us fall through the rating priority chain.
    cursor.execute("""
        SELECT
            b.id,
            b.embedding::text,
            gr.my_rating,
            ul.user_rating,
            ul.is_finished,
            ul.percent_complete
        FROM user_libraries ul
        JOIN books b ON b.id = ul.book_id
        LEFT JOIN book_isbn_asin_map biam ON biam.asin = b.asin
        LEFT JOIN goodreads_books gr ON gr.id = biam.goodreads_book_id
        WHERE ul.user_id = %s
          AND b.embedding IS NOT NULL
    """, (user_id,))

    rows = cursor.fetchall()
    if not rows:
        return (None, 0)

    weighted_sum = [0.0] * EMBEDDING_DIMS
    weight_sum = 0.0
    books_count = 0

    for row in rows:
        _book_id, emb_str, gr_rating, user_rating, is_finished, pct_complete = row

        embedding = _parse_pgvector(emb_str)
        if embedding is None or len(embedding) != EMBEDDING_DIMS:
            continue

        # Determine best rating
        rating = None
        if gr_rating is not None and gr_rating > 0:
            rating = float(gr_rating)
        elif user_rating is not None and user_rating > 0:
            rating = float(user_rating)
        elif is_finished:
            rating = 3.5
        elif pct_complete is not None and float(pct_complete) > 50:
            rating = 3.0

        if rating is None or rating <= 0:
            continue

        # Accumulate weighted embedding
        for i in range(EMBEDDING_DIMS):
            weighted_sum[i] += rating * embedding[i]
        weight_sum += rating
        books_count += 1

    if books_count == 0 or weight_sum == 0:
        return (None, 0)

    # Normalize to centroid
    centroid = [x / weight_sum for x in weighted_sum]
    return (centroid, books_count)


def build_profile_context(cursor, user_id: int) -> dict:
    """Query structured reading stats for the LLM prompt.

    Returns dict with keys: top_books, genre_distribution, avg_runtime,
    median_runtime, completion_rate, total_books, finished_books.
    """
    # Top 10 rated books (same rating priority)
    cursor.execute("""
        SELECT
            b.title,
            COALESCE(
                STRING_AGG(DISTINCT a.name, ', ') FILTER (WHERE a.name IS NOT NULL),
                'Unknown'
            ) AS authors,
            COALESCE(
                STRING_AGG(DISTINCT c.name, ', ') FILTER (WHERE c.name IS NOT NULL),
                ''
            ) AS categories,
            COALESCE(gr.my_rating, ul.user_rating, CASE WHEN ul.is_finished THEN 3.5 ELSE NULL END) AS best_rating,
            b.runtime_length_min
        FROM user_libraries ul
        JOIN books b ON b.id = ul.book_id
        LEFT JOIN book_authors ba ON ba.book_id = b.id
        LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN book_categories bc ON bc.book_id = b.id
        LEFT JOIN categories c ON c.id = bc.category_id
        LEFT JOIN book_isbn_asin_map biam ON biam.asin = b.asin
        LEFT JOIN goodreads_books gr ON gr.id = biam.goodreads_book_id
        WHERE ul.user_id = %s
        GROUP BY b.id, b.title, gr.my_rating, ul.user_rating, ul.is_finished, b.runtime_length_min
        HAVING COALESCE(gr.my_rating, ul.user_rating, CASE WHEN ul.is_finished THEN 3.5 ELSE NULL END) IS NOT NULL
        ORDER BY COALESCE(gr.my_rating, ul.user_rating, CASE WHEN ul.is_finished THEN 3.5 ELSE NULL END) DESC,
                 b.title
        LIMIT 10
    """, (user_id,))

    top_books = []
    for row in cursor.fetchall():
        top_books.append({
            "title": row[0],
            "authors": row[1],
            "categories": row[2],
            "rating": float(row[3]) if row[3] else None,
            "runtime_min": row[4],
        })

    # Genre distribution
    cursor.execute("""
        SELECT c.name, COUNT(*) AS cnt
        FROM user_libraries ul
        JOIN books b ON b.id = ul.book_id
        JOIN book_categories bc ON bc.book_id = b.id
        JOIN categories c ON c.id = bc.category_id
        WHERE ul.user_id = %s
        GROUP BY c.name
        ORDER BY cnt DESC
        LIMIT 15
    """, (user_id,))

    genre_distribution = {row[0]: row[1] for row in cursor.fetchall()}

    # Runtime stats
    cursor.execute("""
        SELECT
            AVG(b.runtime_length_min),
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.runtime_length_min)
        FROM user_libraries ul
        JOIN books b ON b.id = ul.book_id
        WHERE ul.user_id = %s
          AND b.runtime_length_min IS NOT NULL
          AND b.runtime_length_min > 0
    """, (user_id,))

    runtime_row = cursor.fetchone()
    avg_runtime = round(float(runtime_row[0]), 1) if runtime_row and runtime_row[0] else None
    median_runtime = round(float(runtime_row[1]), 1) if runtime_row and runtime_row[1] else None

    # Completion stats
    cursor.execute("""
        SELECT
            COUNT(*),
            SUM(CASE WHEN is_finished THEN 1 ELSE 0 END)
        FROM user_libraries
        WHERE user_id = %s
    """, (user_id,))

    comp_row = cursor.fetchone()
    total_books = comp_row[0] if comp_row else 0
    finished_books = comp_row[1] if comp_row else 0
    completion_rate = round(finished_books / total_books, 2) if total_books > 0 else 0.0

    return {
        "top_books": top_books,
        "genre_distribution": genre_distribution,
        "avg_runtime": avg_runtime,
        "median_runtime": median_runtime,
        "completion_rate": completion_rate,
        "total_books": total_books,
        "finished_books": finished_books,
    }


def _format_profile_prompt(context: dict) -> list[dict]:
    """Format the profile context into OpenAI chat messages."""
    # Build the user message with concrete details
    parts = []

    if context["top_books"]:
        parts.append("Top-rated books:")
        for b in context["top_books"]:
            line = f"  - \"{b['title']}\" by {b['authors']}"
            if b["categories"]:
                line += f" ({b['categories']})"
            if b["rating"]:
                line += f" — rated {b['rating']}/5"
            parts.append(line)

    if context["genre_distribution"]:
        genre_str = ", ".join(
            f"{name} ({count})" for name, count in context["genre_distribution"].items()
        )
        parts.append(f"\nGenre distribution: {genre_str}")

    if context["avg_runtime"]:
        parts.append(
            f"\nAverage audiobook length: {context['avg_runtime']} min "
            f"(~{context['avg_runtime'] / 60:.1f} hrs)"
        )
    if context["median_runtime"]:
        parts.append(
            f"Median audiobook length: {context['median_runtime']} min "
            f"(~{context['median_runtime'] / 60:.1f} hrs)"
        )

    parts.append(
        f"\nLibrary: {context['total_books']} books, "
        f"{context['finished_books']} finished "
        f"({context['completion_rate']:.0%} completion rate)"
    )

    user_content = "\n".join(parts)

    system_msg = (
        "You are a literary taste analyst. Given a listener's audiobook data — "
        "their top-rated titles, genre breakdown, and listening stats — write a "
        "2-3 paragraph profile of their reading taste. Be specific: name genres, "
        "themes, and patterns you see. Mention what they seem to value (narration "
        "quality, story complexity, series loyalty, etc). Write in second person "
        "(\"You tend to...\"). Keep it under 200 words."
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]


def generate_taste_profile(
    cursor, user_id: int, client=None
) -> Optional[str]:
    """Compute taste vector, build context, generate LLM profile, and store.

    Args:
        cursor: Database cursor (caller manages transaction).
        user_id: User ID to generate profile for.
        client: Optional OpenAI client (for testing). Created from env if None.

    Returns:
        The generated profile text, or None if no eligible books.
    """
    # Step 1: Compute taste vector
    vector, books_count = compute_taste_vector(cursor, user_id)
    if vector is None:
        logger.info("No eligible books for user %d — skipping profile generation", user_id)
        return None

    # Step 2: Build structured context for the LLM
    context = build_profile_context(cursor, user_id)

    # Step 3: Call LLM
    if client is None:
        client = _get_openai_client()

    messages = _format_profile_prompt(context)
    response = client.chat.completions.create(
        model=PROFILE_MODEL,
        messages=messages,
        max_tokens=PROFILE_MAX_TOKENS,
        temperature=0.7,
    )

    # Validate response structure
    if (
        not response.choices
        or not response.choices[0].message
        or not response.choices[0].message.content
    ):
        raise ValueError(
            "OpenAI response missing expected content: "
            f"choices={getattr(response, 'choices', None)}"
        )

    profile_text = response.choices[0].message.content.strip()

    # Step 4: Upsert into taste_profiles
    vector_str = "[" + ",".join(str(x) for x in vector) + "]"
    cursor.execute("""
        INSERT INTO taste_profiles (user_id, taste_vector, profile_text, books_included, generated_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            taste_vector = EXCLUDED.taste_vector,
            profile_text = EXCLUDED.profile_text,
            books_included = EXCLUDED.books_included,
            generated_at = NOW(),
            updated_at = NOW()
    """, (user_id, vector_str, profile_text, books_count))

    logger.info(
        "Generated taste profile for user %d: %d books, %d chars",
        user_id, books_count, len(profile_text),
    )

    return profile_text
