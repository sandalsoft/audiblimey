"""Recommendation candidate generation for audiblimey.

The scoring/explainability engine (``engine/scoring.py``) and the
``/api/recommendations`` read path already turn ``user_recommendations`` rows
into ranked, explained suggestions. The missing piece — supplied here — is
*populating* that table with books the user does not own.

``generate_recommendations`` reuses the existing preference signals
(author/narrator affinity, incomplete series) to decide *what* to fetch from the
Audible catalog (``sync/catalog.py``), stores each unowned candidate via
``store_book(..., in_library=False)``, and upserts one row per book into
``user_recommendations``. Scoring stays in the read path — this module only
provides candidates and the source (suggestion_type/source_name) that the
scorer keys off.
"""

import logging

from audiblimey.db import get_cursor
from audiblimey.engine.embeddings import run_embedding_pipeline
from audiblimey.engine.scoring import (
    get_author_scores,
    get_narrator_scores,
)
from audiblimey.engine.taste import excluded_book_ids
from audiblimey.sync.audible import client_from_db, store_book
from audiblimey.sync.catalog import fetch_series_products, search_catalog

logger = logging.getLogger(__name__)

# How many top affinity entities to expand into catalog searches.
TOP_AUTHORS = 8
TOP_NARRATORS = 5

# Strongest-source wins when one book is reachable via multiple signals.
_SOURCE_PRIORITY = {"series": 3, "author": 2, "narrator": 1}


def _owned_asins(cur, user_id: int) -> set[str]:
    cur.execute(
        """
        SELECT b.asin
        FROM user_libraries ul
        JOIN books b ON ul.book_id = b.id
        WHERE ul.user_id = %s
        """,
        (user_id,),
    )
    return {r[0] for r in cur.fetchall()}


def _owned_series_titles(cur, user_id: int, excluded: set[int]) -> list[str]:
    """Every series the user owns at least one (non-excluded) book in.

    Series candidates must be driven by ownership, not by get_series_progress:
    the DB only holds owned books until the catalog is fetched, so a series
    can't be detected as "incomplete" until *after* its full membership is
    ingested here.
    """
    cur.execute(
        """
        SELECT DISTINCT s.title
        FROM series s
        JOIN book_series bs ON s.id = bs.series_id
        JOIN user_libraries ul ON bs.book_id = ul.book_id
        WHERE ul.user_id = %s
          AND bs.book_id <> ALL(%s::bigint[])
        """,
        (user_id, list(excluded)),
    )
    return [r[0] for r in cur.fetchall()]


def _top_names(scores: dict, limit: int) -> list[str]:
    """Top entity names by weighted score, breaking ties on book_count."""
    ranked = sorted(
        scores.items(),
        key=lambda kv: (kv[1]["weighted_score"], kv[1]["book_count"]),
        reverse=True,
    )
    return [name for name, _ in ranked[:limit]]


def generate_recommendations(user_id: int = 1, client=None) -> dict:
    """Fetch unowned candidate books and upsert them into user_recommendations.

    Returns a summary dict: candidate count and how many of each signal drove it.
    """
    if client is None:
        client = client_from_db(user_id)

    with get_cursor() as cur:
        excluded = excluded_book_ids(cur, user_id)
        owned = _owned_asins(cur, user_id)
        owned_series = _owned_series_titles(cur, user_id, excluded)

    author_scores = get_author_scores(user_id, excluded_ids=excluded)
    narrator_scores = get_narrator_scores(user_id, excluded_ids=excluded)

    top_authors = _top_names(author_scores, TOP_AUTHORS)
    top_narrators = _top_names(narrator_scores, TOP_NARRATORS)

    # asin -> {product, stype, source}; strongest source kept per book.
    candidates: dict[str, dict] = {}

    def add(product: dict, stype: str, source: str) -> None:
        asin = product.get("asin")
        if not asin or asin in owned:
            return
        existing = candidates.get(asin)
        if existing and _SOURCE_PRIORITY[existing["stype"]] >= _SOURCE_PRIORITY[stype]:
            return
        candidates[asin] = {"product": product, "stype": stype, "source": source}

    # Every started series — surfaces missing entries AND new releases. Ingesting
    # the full membership also lets get_series_progress flag these as incomplete.
    for title in owned_series:
        for product in fetch_series_products(client, title):
            add(product, "series", title)

    # Favorite authors / narrators.
    for name in top_authors:
        for product in search_catalog(client, author=name):
            add(product, "author", name)
    for name in top_narrators:
        for product in search_catalog(client, narrator=name):
            add(product, "narrator", name)

    # Store candidates + upsert recommendation rows (one row per book).
    inserted = 0
    with get_cursor() as cur:
        for asin, cand in candidates.items():
            cur.execute("SAVEPOINT cand")
            try:
                book_id = store_book(cur, user_id, cand["product"], in_library=False)
                if book_id is None:
                    cur.execute("RELEASE SAVEPOINT cand")
                    continue
                cur.execute(
                    """
                    INSERT INTO user_recommendations
                        (user_id, book_id, suggestion_type, source_name)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, book_id) DO UPDATE SET
                        suggestion_type = EXCLUDED.suggestion_type,
                        source_name = EXCLUDED.source_name,
                        generated_at = NOW()
                    """,
                    (user_id, book_id, cand["stype"], cand["source"]),
                )
                cur.execute("RELEASE SAVEPOINT cand")
                inserted += 1
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT cand")
                logger.warning("Failed to store candidate %s: %s", asin, exc)

    # Embed newly ingested books so similarity/taste signals work. Runs on its
    # own connection (needs the committed rows above) and is best-effort — a
    # missing OPENAI_API_KEY must not fail the sync.
    try:
        run_embedding_pipeline()
    except Exception as exc:
        logger.warning("Embedding generation skipped: %s", exc)

    summary = {
        "candidates": inserted,
        "authors": len(top_authors),
        "narrators": len(top_narrators),
        "series": len(owned_series),
    }
    logger.info("generate_recommendations: %s", summary)
    return summary
