"""Tests for Audible catalog discovery (sync/catalog.py)."""

from unittest.mock import MagicMock

from audiblimey.sync.catalog import fetch_series_products, search_catalog


def _client(products):
    """A mock Audible client whose catalog query returns the given products."""
    client = MagicMock()
    client.get.return_value = {"products": products}
    return client


def test_search_catalog_by_author_returns_products():
    products = [{"asin": "B001", "title": "Book One"}]
    client = _client(products)

    result = search_catalog(client, author="Brandon Sanderson")

    assert result == products
    # Author param is forwarded to the catalog endpoint.
    _, kwargs = client.get.call_args
    assert kwargs["author"] == "Brandon Sanderson"
    assert client.get.call_args[0][0] == "1.0/catalog/products"


def test_search_catalog_with_no_terms_returns_empty_without_calling_api():
    client = _client([{"asin": "B001"}])

    assert search_catalog(client) == []
    client.get.assert_not_called()


def test_search_catalog_swallows_api_errors():
    client = MagicMock()
    client.get.side_effect = RuntimeError("network down")

    assert search_catalog(client, keywords="anything") == []


def test_fetch_series_products_filters_to_matching_series():
    products = [
        {"asin": "B001", "title": "Mistborn 1", "series": [{"title": "Mistborn"}]},
        {"asin": "B002", "title": "Unrelated", "series": [{"title": "Stormlight"}]},
        {"asin": "B003", "title": "No series info"},
    ]
    client = _client(products)

    result = fetch_series_products(client, "Mistborn")

    assert [p["asin"] for p in result] == ["B001"]


def test_fetch_series_products_empty_title_returns_empty():
    client = _client([{"asin": "B001"}])

    assert fetch_series_products(client, "") == []
    client.get.assert_not_called()
