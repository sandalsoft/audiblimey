"""Audible catalog discovery — fetch books the user does NOT own.

Library sync (``audible.py``) only reads the user's own purchases. This module
queries the public catalog (``1.0/catalog/products``) to discover candidate
books — by author, by narrator, and the full membership of series the user has
started — so the recommendation engine and "Continue Your Series" have unowned
books to surface. Results are shape-compatible with ``store_book`` and are
stored with ``in_library=False``.
"""

import logging

logger = logging.getLogger(__name__)

# Same product detail groups as library sync, minus the library-only groups
# (is_finished, percent_complete, listening_status, rating).
CATALOG_RESPONSE_GROUPS = "contributors,product_desc,media,price,series"


def _catalog_search(client, *, num_results: int = 50, **params) -> list[dict]:
    """Run one catalog/products query and return the product dicts.

    Network/API failures are logged and swallowed (returns []) so a single
    failed query never aborts a whole sync.
    """
    try:
        response = client.get(
            "1.0/catalog/products",
            num_results=num_results,
            response_groups=CATALOG_RESPONSE_GROUPS,
            image_sizes="1215,500",
            **params,
        )
    except Exception as exc:
        logger.warning("Catalog search failed (%s): %s", params, exc)
        return []

    products = response.get("products") if isinstance(response, dict) else None
    return products or []


def search_catalog(
    client,
    *,
    keywords: str | None = None,
    author: str | None = None,
    narrator: str | None = None,
    num_results: int = 50,
) -> list[dict]:
    """Search the Audible catalog by keywords / author / narrator.

    Returns a list of product dicts ready to hand to ``store_book``.
    """
    params: dict = {}
    if keywords:
        params["keywords"] = keywords
    if author:
        params["author"] = author
    if narrator:
        params["narrator"] = narrator
    if not params:
        return []
    return _catalog_search(client, num_results=num_results, **params)


def fetch_series_products(client, series_title: str, num_results: int = 50) -> list[dict]:
    """Fetch all catalog entries belonging to a series.

    Searches by the series title, then keeps only products whose ``series``
    membership actually matches — a keyword search alone returns loosely
    related titles. This surfaces newly released entries the user hasn't
    bought yet (the "search for new releases in started series" feature).
    """
    if not series_title:
        return []

    target = series_title.strip().lower()
    products = _catalog_search(client, num_results=num_results, keywords=series_title)

    matched = []
    for product in products:
        for series in product.get("series") or []:
            name = (series.get("title") or "").strip().lower()
            if name and (name == target or target in name or name in target):
                matched.append(product)
                break
    return matched
