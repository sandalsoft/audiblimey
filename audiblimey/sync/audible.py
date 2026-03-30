"""Audible library sync — fetch from Audible API and store in PostgreSQL.

Ported from AudiPy's phase3_fetch_library.py (MySQL → PostgreSQL).
"""

import json
import logging
from datetime import datetime, timezone

from audiblimey.db import get_cursor

logger = logging.getLogger(__name__)


def _parse_datetime(datetime_str):
    """Parse datetime string from Audible API to Python datetime.

    Handles ISO 8601 with 'Z' suffix and various Audible formats.
    Returns None for unparseable values rather than raising.
    """
    if not datetime_str:
        return None
    try:
        if isinstance(datetime_str, str):
            if datetime_str.endswith("Z"):
                datetime_str = datetime_str[:-1] + "+00:00"
            return datetime.fromisoformat(datetime_str)
        return datetime_str
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to parse datetime '%s': %s", datetime_str, exc)
        return None


def store_book(cur, user_id: int, book_data: dict) -> int | None:
    """Store a single book and its relationships in PostgreSQL.

    Upserts the book, deduplicates authors/narrators/series by name,
    links them via junction tables, and upserts the user_library entry.

    Returns the book ID on success, None if the book is skipped
    (missing ASIN or missing title).
    """
    asin = book_data.get("asin")
    if not asin:
        logger.warning("Skipping book with missing ASIN: %s", book_data.get("title", "<untitled>"))
        return None

    title = book_data.get("title", "")
    if not title:
        logger.warning("Skipping book %s with empty title", asin)
        return None

    publication_datetime = _parse_datetime(book_data.get("publication_datetime"))

    # -- Upsert book --------------------------------------------------------
    cur.execute(
        """
        INSERT INTO books (
            asin, title, subtitle, publisher_name, publication_datetime,
            language, content_type, runtime_length_min,
            merchandising_summary, extended_product_description
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (asin) DO UPDATE SET
            title = EXCLUDED.title,
            subtitle = EXCLUDED.subtitle,
            publisher_name = EXCLUDED.publisher_name,
            publication_datetime = EXCLUDED.publication_datetime,
            language = EXCLUDED.language,
            content_type = EXCLUDED.content_type,
            runtime_length_min = EXCLUDED.runtime_length_min,
            merchandising_summary = EXCLUDED.merchandising_summary,
            extended_product_description = EXCLUDED.extended_product_description
        RETURNING id
        """,
        (
            asin,
            title,
            book_data.get("subtitle"),
            book_data.get("publisher_name"),
            publication_datetime,
            book_data.get("language", ""),
            book_data.get("content_type"),
            book_data.get("runtime_length_min"),
            book_data.get("merchandising_summary"),
            book_data.get("extended_product_description"),
        ),
    )
    row = cur.fetchone()
    book_id = row[0]

    # -- Authors -------------------------------------------------------------
    authors = book_data.get("authors") or []
    for idx, author in enumerate(authors):
        author_name = author.get("name")
        if not author_name:
            continue
        author_asin = author.get("asin")

        # Dedup by name: authors.asin is nullable and not all authors have ASINs
        if author_asin:
            cur.execute(
                """
                INSERT INTO authors (name, asin)
                VALUES (%s, %s)
                ON CONFLICT (asin) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (author_name, author_asin),
            )
        else:
            # No ASIN — look up by name, insert if not found
            cur.execute("SELECT id FROM authors WHERE name = %s LIMIT 1", (author_name,))
            existing = cur.fetchone()
            if existing:
                cur.execute("SELECT id FROM authors WHERE id = %s", (existing[0],))
            else:
                cur.execute(
                    "INSERT INTO authors (name) VALUES (%s) RETURNING id",
                    (author_name,),
                )

        author_row = cur.fetchone()
        author_id = author_row[0]

        cur.execute(
            """
            INSERT INTO book_authors (book_id, author_id, display_order)
            VALUES (%s, %s, %s)
            ON CONFLICT (book_id, author_id) DO NOTHING
            """,
            (book_id, author_id, idx),
        )

    # -- Narrators -----------------------------------------------------------
    narrators = book_data.get("narrators") or []
    for idx, narrator in enumerate(narrators):
        narrator_name = narrator.get("name")
        if not narrator_name:
            continue
        narrator_asin = narrator.get("asin")

        if narrator_asin:
            cur.execute(
                """
                INSERT INTO narrators (name, asin)
                VALUES (%s, %s)
                ON CONFLICT (asin) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (narrator_name, narrator_asin),
            )
        else:
            cur.execute("SELECT id FROM narrators WHERE name = %s LIMIT 1", (narrator_name,))
            existing = cur.fetchone()
            if existing:
                cur.execute("SELECT id FROM narrators WHERE id = %s", (existing[0],))
            else:
                cur.execute(
                    "INSERT INTO narrators (name) VALUES (%s) RETURNING id",
                    (narrator_name,),
                )

        narrator_row = cur.fetchone()
        narrator_id = narrator_row[0]

        cur.execute(
            """
            INSERT INTO book_narrators (book_id, narrator_id, display_order)
            VALUES (%s, %s, %s)
            ON CONFLICT (book_id, narrator_id) DO NOTHING
            """,
            (book_id, narrator_id, idx),
        )

    # -- Series --------------------------------------------------------------
    series_list = book_data.get("series") or []
    for series in series_list:
        series_title = series.get("title")
        if not series_title:
            continue
        series_asin = series.get("asin")

        if series_asin:
            cur.execute(
                """
                INSERT INTO series (title, asin)
                VALUES (%s, %s)
                ON CONFLICT (asin) DO UPDATE SET title = EXCLUDED.title
                RETURNING id
                """,
                (series_title, series_asin),
            )
        else:
            cur.execute("SELECT id FROM series WHERE title = %s LIMIT 1", (series_title,))
            existing = cur.fetchone()
            if existing:
                cur.execute("SELECT id FROM series WHERE id = %s", (existing[0],))
            else:
                cur.execute(
                    "INSERT INTO series (title) VALUES (%s) RETURNING id",
                    (series_title,),
                )

        series_row = cur.fetchone()
        series_id = series_row[0]

        sequence = series.get("sequence")
        cur.execute(
            """
            INSERT INTO book_series (book_id, series_id, sequence, sequence_display)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (book_id, series_id) DO NOTHING
            """,
            (book_id, series_id, sequence, str(sequence) if sequence else None),
        )

    # -- User library entry --------------------------------------------------
    purchase_date = _parse_datetime(book_data.get("purchase_date"))

    cur.execute(
        """
        INSERT INTO user_libraries (
            user_id, book_id, purchase_date,
            percent_complete, is_finished
        ) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id, book_id) DO UPDATE SET
            purchase_date = EXCLUDED.purchase_date,
            percent_complete = EXCLUDED.percent_complete,
            is_finished = EXCLUDED.is_finished
        """,
        (
            user_id,
            book_id,
            purchase_date,
            book_data.get("percent_complete", 0),
            book_data.get("is_finished", False),
        ),
    )

    return book_id


def fetch_audible_library(auth_data: dict, marketplace: str = "us") -> list[dict]:
    """Fetch user's library from Audible API.

    Creates an Audible client from stored auth dict, fetches up to 1000
    items per page with pagination support.

    Returns list of book dicts from the Audible API.
    Raises on auth or network errors — callers should handle.
    """
    from audible import Authenticator, Client

    auth = Authenticator.from_dict(auth_data)
    client = Client(auth=auth)

    all_items = []
    page_size = 1000
    page = 1

    while True:
        response = client.get(
            "1.0/library",
            num_results=page_size,
            page=page,
            response_groups="series,contributors,product_desc,media,price",
        )
        items = response.get("items", [])
        all_items.extend(items)

        total = response.get("total_results", len(items))
        if len(all_items) >= total or not items:
            break
        page += 1

    return all_items


def run_sync(user_id: int, job_id: int):
    """Orchestrate a full Audible library sync.

    1. Load auth data from user_audible_accounts
    2. Fetch library from Audible API
    3. Store each book in PostgreSQL
    4. Update sync_jobs with progress/completion/failure

    Designed to run in a FastAPI BackgroundTask.
    """
    logger.info("sync.run_sync started: user_id=%d, job_id=%d", user_id, job_id)

    # Mark job as running
    try:
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE sync_jobs
                SET status = 'running', started_at = NOW()
                WHERE id = %s
                """,
                (job_id,),
            )
    except Exception as exc:
        logger.error("sync.run_sync: failed to mark job %d as running: %s", job_id, exc)
        return

    try:
        # -- Load auth data --------------------------------------------------
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT encrypted_auth_data, marketplace
                FROM user_audible_accounts
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            account_row = cur.fetchone()

        if not account_row:
            _fail_job(job_id, "No Audible account configured for user")
            return

        encrypted_auth_data, marketplace = account_row

        # For now, auth_data is stored as JSON text (encryption handled at
        # a higher layer — the column is encrypted_auth_data but this module
        # receives the data as-is from the DB).
        try:
            auth_data = json.loads(encrypted_auth_data)
        except (json.JSONDecodeError, TypeError) as exc:
            _fail_job(job_id, f"Invalid auth data: {exc}")
            return

        # -- Fetch library ---------------------------------------------------
        try:
            library_items = fetch_audible_library(auth_data, marketplace or "us")
        except Exception as exc:
            _fail_job(job_id, f"Audible API error: {exc}")
            return

        # -- Store books -----------------------------------------------------
        books_processed = 0
        books_added = 0
        books_updated = 0

        with get_cursor() as cur:
            for book_data in library_items:
                try:
                    book_id = store_book(cur, user_id, book_data)
                    if book_id is not None:
                        books_processed += 1
                        # We can't easily distinguish add vs update from
                        # ON CONFLICT, so count all as processed.
                        books_added += 1
                except Exception as exc:
                    logger.warning(
                        "sync.run_sync: failed to store book %s: %s",
                        book_data.get("asin", "?"),
                        exc,
                    )
                    continue

        # -- Mark job complete -----------------------------------------------
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE sync_jobs
                SET status = 'completed',
                    completed_at = NOW(),
                    books_processed = %s,
                    books_added = %s,
                    books_updated = %s
                WHERE id = %s
                """,
                (books_processed, books_added, books_updated, job_id),
            )

        # Update account sync status
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE user_audible_accounts
                SET sync_status = 'completed', last_sync = NOW()
                WHERE user_id = %s
                """,
                (user_id,),
            )

        logger.info(
            "sync.run_sync completed: job_id=%d, books_processed=%d",
            job_id, books_processed,
        )

    except Exception as exc:
        logger.error("sync.run_sync: unexpected error in job %d: %s", job_id, exc)
        _fail_job(job_id, f"Unexpected error: {exc}")


def _fail_job(job_id: int, error_message: str):
    """Mark a sync job as failed with an error message."""
    logger.error("sync job %d failed: %s", job_id, error_message)
    try:
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE sync_jobs
                SET status = 'failed',
                    completed_at = NOW(),
                    error_message = %s
                WHERE id = %s
                """,
                (error_message, job_id),
            )
    except Exception as exc:
        logger.error("sync._fail_job: could not update job %d: %s", job_id, exc)
