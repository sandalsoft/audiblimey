"""Audible library sync — fetch from Audible API and store in PostgreSQL.

Ported from AudiPy's phase3_fetch_library.py (MySQL → PostgreSQL).
"""

import json
import logging
import re
from datetime import datetime, timezone

from psycopg2.extras import Json

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


def _collect_image_urls(value) -> list[str]:
    """Collect plausible image URLs from Audible's loosely documented media payload."""
    urls: list[str] = []

    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            urls.append(value)
        return urls

    if isinstance(value, list):
        for item in value:
            urls.extend(_collect_image_urls(item))
        return urls

    if isinstance(value, dict):
        for item in value.values():
            urls.extend(_collect_image_urls(item))

    return urls


def _best_product_image_url(product_images) -> str | None:
    if not isinstance(product_images, dict):
        return None

    candidates: list[tuple[int, str]] = []
    for key, value in product_images.items():
        urls = _collect_image_urls(value)
        if not urls:
            continue
        try:
            size = int(key)
        except (TypeError, ValueError):
            size = 0
        candidates.extend((size, url) for url in urls)

    if not candidates:
        return None

    return max(candidates, key=lambda item: (item[0], len(item[1])))[1]


def _best_image_url(book_data: dict) -> str | None:
    """Pick the largest-looking image URL from known Audible image fields."""
    product_image_url = _best_product_image_url(book_data.get("product_images"))
    if product_image_url:
        return product_image_url

    image_url = book_data.get("image_url")
    if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
        return image_url

    candidates: list[str] = []
    for key in ("rich_images", "social_media_images"):
        candidates.extend(_collect_image_urls(book_data.get(key)))

    if not candidates:
        return None

    def score(url: str) -> tuple[int, int]:
        dimensions = [int(n) for n in re.findall(r"(?<!\d)(\d{2,4})(?!\d)", url)]
        return (max(dimensions) if dimensions else 0, len(url))

    return max(dict.fromkeys(candidates), key=score)


def _cache_image_metadata(cur, book_id: int, book_data: dict) -> None:
    product_images = book_data.get("product_images")
    social_media_images = book_data.get("social_media_images")
    rich_images = book_data.get("rich_images")
    image_url = _best_image_url(book_data)

    if not any(value is not None for value in (product_images, social_media_images, rich_images, image_url)):
        return

    cur.execute(
        """
        INSERT INTO book_extended_data (
            book_id, product_images, social_media_images, rich_images, image_url
        ) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (book_id) DO UPDATE SET
            product_images = COALESCE(EXCLUDED.product_images, book_extended_data.product_images),
            social_media_images = COALESCE(EXCLUDED.social_media_images, book_extended_data.social_media_images),
            rich_images = COALESCE(EXCLUDED.rich_images, book_extended_data.rich_images),
            image_url = COALESCE(EXCLUDED.image_url, book_extended_data.image_url)
        """,
        (
            book_id,
            Json(product_images) if product_images is not None else None,
            Json(social_media_images) if social_media_images is not None else None,
            Json(rich_images) if rich_images is not None else None,
            image_url,
        ),
    )


def _fetch_catalog_media(client, asin: str) -> dict | None:
    try:
        response = client.get(
            f"1.0/catalog/products/{asin}",
            response_groups="media",
            image_sizes="1215,500",
        )
    except Exception as exc:
        logger.warning("Failed to fetch catalog media for %s: %s", asin, exc)
        return None

    product = response.get("product") if isinstance(response, dict) else None
    if isinstance(product, dict):
        return product
    return response if isinstance(response, dict) else None


def store_book(cur, user_id: int, book_data: dict, in_library: bool = True) -> int | None:
    """Store a single book and its relationships in PostgreSQL.

    Upserts the book, deduplicates authors/narrators/series by name, and links
    them via junction tables. When ``in_library`` is True (library sync), also
    upserts the user_library entry. Catalog-discovered books the user does not
    own are stored with ``in_library=False`` and get no user_library row — that
    absence is how the rest of the app represents "unowned".

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
    release_date = _parse_datetime(book_data.get("release_date"))

    # -- Upsert book --------------------------------------------------------
    cur.execute(
        """
        INSERT INTO books (
            asin, title, subtitle, publisher_name, publication_datetime,
            release_date, language, content_type, runtime_length_min,
            merchandising_summary, extended_product_description
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (asin) DO UPDATE SET
            title = EXCLUDED.title,
            subtitle = EXCLUDED.subtitle,
            publisher_name = EXCLUDED.publisher_name,
            publication_datetime = EXCLUDED.publication_datetime,
            release_date = COALESCE(EXCLUDED.release_date, books.release_date),
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
            release_date,
            book_data.get("language", ""),
            book_data.get("content_type"),
            book_data.get("runtime_length_min"),
            book_data.get("merchandising_summary"),
            book_data.get("extended_product_description"),
        ),
    )
    row = cur.fetchone()
    book_id = row[0]

    # -- Extended image metadata --------------------------------------------
    _cache_image_metadata(cur, book_id, book_data)

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

        raw_sequence = series.get("sequence")
        sequence_display = str(raw_sequence) if raw_sequence else None

        # sequence column is DECIMAL — parse to a number.
        # Audible sends compound values like "1-6" for omnibus editions;
        # use the first number for sorting, keep the raw string in display.
        sequence_numeric = None
        if raw_sequence is not None:
            raw_str = str(raw_sequence).strip()
            try:
                sequence_numeric = float(raw_str)
            except ValueError:
                # Try extracting the leading number from e.g. "1-6", "3.5-4"
                match = re.match(r"^([0-9]+(?:\.[0-9]+)?)", raw_str)
                if match:
                    sequence_numeric = float(match.group(1))

        cur.execute(
            """
            INSERT INTO book_series (book_id, series_id, sequence, sequence_display)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (book_id, series_id) DO NOTHING
            """,
            (book_id, series_id, sequence_numeric, sequence_display),
        )

    # -- User library entry --------------------------------------------------
    # Catalog-discovered (unowned) books get no user_library row.
    if not in_library:
        return book_id

    purchase_date = _parse_datetime(book_data.get("purchase_date"))

    # Audible's rating response_group nests under "rating"
    rating_obj = book_data.get("rating") or {}
    user_rating = rating_obj.get("overall_distribution", {}).get("display_average_rating") if isinstance(rating_obj, dict) else None

    cur.execute(
        """
        INSERT INTO user_libraries (
            user_id, book_id, purchase_date,
            percent_complete, is_finished, user_rating
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, book_id) DO UPDATE SET
            purchase_date = EXCLUDED.purchase_date,
            percent_complete = EXCLUDED.percent_complete,
            is_finished = EXCLUDED.is_finished,
            user_rating = COALESCE(EXCLUDED.user_rating, user_libraries.user_rating)
        """,
        (
            user_id,
            book_id,
            purchase_date,
            book_data.get("percent_complete", 0),
            book_data.get("is_finished", False),
            user_rating,
        ),
    )

    return book_id


def create_audible_client(auth_data: dict, timeout: int = 10):
    """Create an authenticated Audible API client from a stored auth dict.

    Shared by library sync and catalog discovery so both use identical auth.
    ``timeout`` is the per-request HTTP timeout (seconds) applied to every call.
    """
    from audible import Authenticator, Client

    auth = Authenticator.from_dict(auth_data)
    return Client(auth=auth, timeout=timeout)


def audible_auth_from_db(user_id: int) -> tuple[dict, str]:
    """Load the latest stored Audible auth payload for a user."""
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
        row = cur.fetchone()

    if not row:
        raise RuntimeError("No Audible account configured for user")

    encrypted_auth_data, marketplace = row
    try:
        auth_data = json.loads(encrypted_auth_data)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(f"Invalid Audible auth data: {exc}") from exc

    return auth_data, marketplace or "us"


def client_from_db(user_id: int, timeout: int = 10):
    """Build an authenticated Audible API client from the user's stored auth."""
    auth_data, _marketplace = audible_auth_from_db(user_id)
    return create_audible_client(auth_data, timeout=timeout)


def fetch_audible_library(auth_data: dict, marketplace: str = "us") -> list[dict]:
    """Fetch user's library from Audible API.

    Creates an Audible client from stored auth dict, fetches up to 1000
    items per page with pagination support.

    Returns list of book dicts from the Audible API.
    Raises on auth or network errors — callers should handle.
    """
    client = create_audible_client(auth_data)

    all_items = []
    page_size = 1000
    page = 1

    while True:
        response = client.get(
            "1.0/library",
            num_results=page_size,
            page=page,
            response_groups="series,contributors,product_desc,media,price,is_finished,percent_complete,listening_status,rating",
            image_sizes="1215,500",
        )
        items = response.get("items", [])
        for item in items:
            if not _best_image_url(item) and item.get("asin"):
                catalog_media = _fetch_catalog_media(client, item["asin"])
                if catalog_media:
                    for key in ("product_images", "social_media_images", "rich_images", "image_url"):
                        if key in catalog_media and key not in item:
                            item[key] = catalog_media[key]
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
        try:
            auth_data, marketplace = audible_auth_from_db(user_id)
        except RuntimeError as exc:
            _fail_job(job_id, str(exc))
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
                    # Savepoint per book so one failure doesn't poison
                    # the whole transaction.
                    cur.execute("SAVEPOINT book_save")
                    book_id = store_book(cur, user_id, book_data)
                    cur.execute("RELEASE SAVEPOINT book_save")
                    if book_id is not None:
                        books_processed += 1
                        # We can't easily distinguish add vs update from
                        # ON CONFLICT, so count all as processed.
                        books_added += 1
                except Exception as exc:
                    cur.execute("ROLLBACK TO SAVEPOINT book_save")
                    logger.warning(
                        "sync.run_sync: failed to store book %s: %s",
                        book_data.get("asin", "?"),
                        exc,
                    )
                    continue

        # -- Discover unowned candidates + regenerate recommendations --------
        # Best-effort: the library sync already succeeded, so a catalog/OpenAI
        # failure here must not fail the job. Imported lazily to avoid a
        # circular import (engine.recommend imports from this module).
        try:
            from audiblimey.engine.recommend import generate_recommendations

            client = create_audible_client(auth_data)
            rec_summary = generate_recommendations(user_id, client=client)
            logger.info("sync.run_sync: recommendations %s", rec_summary)
        except Exception as exc:
            logger.warning("sync.run_sync: recommendation generation failed: %s", exc)

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
