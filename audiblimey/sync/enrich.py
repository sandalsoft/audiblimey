"""Audible product-page enrichment fetch and storage."""

import logging
import re
from typing import Any

import bleach
from psycopg2.extras import Json

from audiblimey.sync.audible import _best_image_url, store_book

logger = logging.getLogger(__name__)

PRODUCT_RESPONSE_GROUPS = (
    "product_desc,product_extended_attrs,rating,category_ladders,"
    "series,contributors,media"
)
RELATED_RESPONSE_GROUPS = "contributors,product_desc,media"
REVIEW_LIMIT = 10
RELATED_LIMIT = 10

# Single source of truth for Audible HTML sanitization: a bleach allowlist.
# Anything not explicitly permitted (tags, attributes, URL schemes) is dropped,
# so the rendered HTML is trusted by the frontend without a second pass.
_ALLOWED_TAGS = [
    "p", "br", "b", "strong", "i", "em", "u",
    "ul", "ol", "li", "blockquote", "h3", "h4", "span", "a",
]
_ALLOWED_ATTRS = {"a": ["href", "title"]}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sanitize_audible_html(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    cleaned = bleach.clean(
        text,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
    return cleaned.strip() or None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        digits = re.sub(r"[^0-9]", "", str(value))
        return int(digits) if digits else None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _product_from_response(response: Any) -> dict:
    if not isinstance(response, dict):
        return {}
    product = response.get("product")
    return product if isinstance(product, dict) else response


def _list_from_response(response: Any, *keys: str) -> list:
    if isinstance(response, list):
        return response
    if not isinstance(response, dict):
        return []
    for key in keys:
        value = response.get(key)
        if isinstance(value, list):
            return value
    return []


def _rating_distribution(rating: dict, key: str) -> dict:
    distribution = rating.get(key) if isinstance(rating, dict) else None
    if not isinstance(distribution, dict):
        distribution = {}
    return {
        "avg": _as_float(distribution.get("display_average_rating")),
        "count": _as_int(distribution.get("num_ratings")),
    }


def _editorial_review_html(review: Any) -> str | None:
    if isinstance(review, str):
        return _sanitize_audible_html(review)
    if not isinstance(review, dict):
        return None
    for key in ("html", "body", "review", "content", "text", "editorial_review"):
        html = _sanitize_audible_html(review.get(key))
        if html:
            return html
    return None


def _author_names(product: dict) -> list[str]:
    authors = product.get("authors") or []
    names = []
    for author in authors:
        if isinstance(author, dict):
            name = _clean_text(author.get("name"))
        else:
            name = _clean_text(author)
        if name:
            names.append(name)
    return names


def _normalize_related(product: dict) -> dict | None:
    asin = _clean_text(product.get("asin"))
    title = _clean_text(product.get("title"))
    if not asin or not title:
        return None
    return {
        "asin": asin,
        "title": title,
        "authors": _author_names(product),
        "image_url": _best_image_url(product),
    }


def _category_node(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = _clean_text(raw.get("name"))
    if not name:
        return None
    return {
        "audible_category_id": _clean_text(raw.get("id") or raw.get("category_id")),
        "name": name,
    }


def _category_paths(category_ladders: Any) -> list[list[dict]]:
    paths: list[list[dict]] = []
    if not isinstance(category_ladders, list):
        return paths

    for ladder in category_ladders:
        raw_path = ladder if isinstance(ladder, list) else None
        if isinstance(ladder, dict):
            for key in ("ladder", "category_ladder", "categories", "nodes", "path"):
                if isinstance(ladder.get(key), list):
                    raw_path = ladder[key]
                    break
            if raw_path is None:
                raw_path = [ladder]
        if not isinstance(raw_path, list):
            continue
        path = [node for node in (_category_node(item) for item in raw_path) if node]
        if path:
            paths.append(path)

    return paths


def _flatten_categories(category_ladders: Any) -> list[dict]:
    seen: set[str] = set()
    categories: list[dict] = []

    for path in _category_paths(category_ladders):
        names: list[str] = []
        for level, node in enumerate(path):
            name = node["name"]
            names.append(name)
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            categories.append({
                "audible_category_id": node.get("audible_category_id"),
                "name": name,
                "parent_name": path[level - 1]["name"] if level else None,
                "level": level,
                "full_path": " > ".join(names),
            })

    return categories


def _normalize_user_review(review: Any) -> dict | None:
    if not isinstance(review, dict):
        return None
    scores = review.get("review_content_scores") or {}
    ratings = review.get("ratings") or {}
    if not isinstance(scores, dict):
        scores = {}
    if not isinstance(ratings, dict):
        ratings = {}

    title = _clean_text(review.get("title"))
    body = _clean_text(review.get("body") or review.get("review"))
    if not title and not body:
        return None

    return {
        "author": _clean_text(review.get("author_name") or review.get("author")),
        "title": title,
        "body": body,
        "date": _clean_text(review.get("submission_date") or review.get("created_at")),
        "overall": _as_float(ratings.get("overall_rating") or review.get("overall_rating")),
        "performance": _as_float(ratings.get("performance_rating") or review.get("performance_rating")),
        "story": _as_float(ratings.get("story_rating") or review.get("story_rating")),
        "helpful_votes": _as_int(
            scores.get("num_helpful_votes")
            or review.get("num_helpful_votes")
            or review.get("helpful_votes")
        ),
    }


def fetch_book_enrichment(client, asin: str) -> dict:
    """Fetch Audible product-page details and normalize them for storage."""
    # The product call carries the essentials (description + ratings); let it
    # raise. The reviews/sims calls are supplementary — guard each so a single
    # failure doesn't discard the product details we already fetched (#3).
    product_response = client.get(
        f"1.0/catalog/products/{asin}",
        response_groups=PRODUCT_RESPONSE_GROUPS,
        image_sizes="500",
    )
    try:
        reviews_response = client.get(
            f"1.0/catalog/products/{asin}/reviews",
            num_results=REVIEW_LIMIT,
            sort_by="MostHelpful",
        )
    except Exception as exc:
        logger.warning("Audible reviews fetch failed for %s: %s", asin, exc)
        reviews_response = {}
    try:
        sims_response = client.get(
            f"1.0/catalog/products/{asin}/sims",
            response_groups=RELATED_RESPONSE_GROUPS,
            image_sizes="500",
        )
    except Exception as exc:
        logger.warning("Audible sims fetch failed for %s: %s", asin, exc)
        sims_response = {}

    product = _product_from_response(product_response)
    rating = product.get("rating") or {}
    category_ladders = product.get("category_ladders")
    categories = _flatten_categories(category_ladders)
    tags = list(dict.fromkeys(cat["name"] for cat in categories))

    raw_editorial_reviews = product.get("editorial_reviews") or []
    if isinstance(raw_editorial_reviews, dict):
        raw_editorial_reviews = [raw_editorial_reviews]
    editorial_reviews = [
        html
        for html in (_editorial_review_html(review) for review in raw_editorial_reviews)
        if html
    ]
    user_reviews = [
        review
        for review in (
            _normalize_user_review(review)
            for review in _list_from_response(reviews_response, "customer_reviews", "reviews")
        )
        if review
    ][:REVIEW_LIMIT]
    related = [
        product
        for product in _list_from_response(sims_response, "similar_products", "products", "items", "sims")
        if isinstance(product, dict)
    ][:RELATED_LIMIT]

    return {
        "full_description": _sanitize_audible_html(product.get("publisher_summary")),
        "tags": tags,
        "categories": categories,
        "ratings": {
            "overall": _rating_distribution(rating, "overall_distribution"),
            "performance": _rating_distribution(rating, "performance_distribution"),
            "story": _rating_distribution(rating, "story_distribution"),
        },
        "editorial_reviews": editorial_reviews,
        "user_reviews": user_reviews,
        "related": related,
    }


def _store_categories(cur, book_id: int, categories: list[dict]) -> None:
    cur.execute("DELETE FROM book_categories WHERE book_id = %s", (book_id,))
    category_ids: dict[str, int] = {}

    for category in categories:
        name = _clean_text(category.get("name"))
        if not name:
            continue
        parent_name = category.get("parent_name")
        parent_id = category_ids.get(parent_name.casefold()) if parent_name else None
        audible_category_id = category.get("audible_category_id")
        level = category.get("level") or 0
        full_path = category.get("full_path") or name

        # Dedup by name via select-then-insert, consistent with how store_book
        # handles authors/narrators/series. Avoids depending on a unique index
        # + ON CONFLICT (name), which would fail to build if the categories
        # table ever held duplicate names.
        cur.execute("SELECT id FROM categories WHERE name = %s LIMIT 1", (name,))
        existing = cur.fetchone()
        if existing:
            category_id = existing[0]
            cur.execute(
                """
                UPDATE categories SET
                    audible_category_id = COALESCE(%s, audible_category_id),
                    parent_id = COALESCE(%s, parent_id),
                    level = %s,
                    full_path = %s
                WHERE id = %s
                """,
                (audible_category_id, parent_id, level, full_path, category_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO categories (audible_category_id, name, parent_id, level, full_path)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (audible_category_id, name, parent_id, level, full_path),
            )
            category_id = cur.fetchone()[0]
        category_ids[name.casefold()] = category_id
        cur.execute(
            """
            INSERT INTO book_categories (book_id, category_id)
            VALUES (%s, %s)
            ON CONFLICT (book_id, category_id) DO NOTHING
            """,
            (book_id, category_id),
        )


def store_book_enrichment(cur, user_id: int, book_id: int, asin: str, data: dict) -> None:
    """Persist normalized Audible enrichment for one book."""
    full_description = data.get("full_description") or None
    if full_description:
        cur.execute(
            "UPDATE books SET publisher_summary = %s WHERE id = %s",
            (full_description, book_id),
        )

    related = []
    for product in data.get("related") or []:
        related_id = store_book(cur, user_id, product, in_library=False)
        if related_id is None:
            logger.debug("Skipping related product without ASIN/title for %s", asin)
            continue
        item = _normalize_related(product)
        if item:
            related.append(item)

    categories = data.get("categories") or []
    if categories:
        _store_categories(cur, book_id, categories)

    ratings = data.get("ratings") or {}
    overall = ratings.get("overall") or {}
    performance = ratings.get("performance") or {}
    story = ratings.get("story") or {}

    cur.execute(
        """
        INSERT INTO book_extended_data (
            book_id,
            tags,
            customer_reviews,
            rating_overall,
            rating_overall_count,
            rating_performance,
            rating_performance_count,
            rating_story,
            rating_story_count,
            editorial_reviews,
            audible_related,
            audible_enriched_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (book_id) DO UPDATE SET
            tags = EXCLUDED.tags,
            customer_reviews = EXCLUDED.customer_reviews,
            rating_overall = EXCLUDED.rating_overall,
            rating_overall_count = EXCLUDED.rating_overall_count,
            rating_performance = EXCLUDED.rating_performance,
            rating_performance_count = EXCLUDED.rating_performance_count,
            rating_story = EXCLUDED.rating_story,
            rating_story_count = EXCLUDED.rating_story_count,
            editorial_reviews = EXCLUDED.editorial_reviews,
            audible_related = EXCLUDED.audible_related,
            audible_enriched_at = EXCLUDED.audible_enriched_at
        """,
        (
            book_id,
            Json(data.get("tags") or []),
            Json(data.get("user_reviews") or []),
            overall.get("avg"),
            overall.get("count"),
            performance.get("avg"),
            performance.get("count"),
            story.get("avg"),
            story.get("count"),
            Json(data.get("editorial_reviews") or []),
            Json(related),
        ),
    )
