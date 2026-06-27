"""Tests for Audible enrichment API routes."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from audiblimey.api.main import app

client = TestClient(app)


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.index = -1

    def execute(self, query, params=None):
        self.index += 1

    def fetchone(self):
        if self.index < len(self.rows):
            return self.rows[self.index]
        return self.rows[-1] if self.rows else None

    def fetchall(self):
        return []

    def close(self):
        pass


@contextmanager
def fake_get_cursor(cursor):
    yield cursor


def enrichment_row(enriched_at):
    return (
        42,
        "<p>Full description</p>",
        ["Espionage"],
        Decimal("4.00"),
        1234,
        Decimal("4.40"),
        900,
        Decimal("4.30"),
        850,
        ["<p>Critic review</p>"],
        [{"author": "Lesley", "helpful_votes": 11}],
        [{"asin": "REL1", "title": "Related Book", "authors": ["A. Writer"], "image_url": None}],
        enriched_at,
        [{"id": 9, "name": "Espionage"}],
    )


@patch("audiblimey.api.routes.enrichment.get_cursor")
@patch("audiblimey.api.routes.enrichment._fetch_and_store")
def test_get_details_serves_fresh_cache_without_audible(mock_fetch, mock_get_cursor):
    cur = FakeCursor([enrichment_row(datetime.now(timezone.utc))])
    mock_get_cursor.side_effect = lambda: fake_get_cursor(cur)

    resp = client.get("/api/books/B002V5GO3O/details")

    assert resp.status_code == 200
    data = resp.json()
    assert data["full_description"] == "<p>Full description</p>"
    assert data["ratings"]["overall"] == {"avg": 4.0, "count": 1234}
    assert data["user_reviews"][0]["helpful_votes"] == 11
    assert data["stale"] is False
    mock_fetch.assert_not_called()


@patch("audiblimey.api.routes.enrichment.get_cursor")
@patch("audiblimey.api.routes.enrichment._fetch_and_store")
def test_get_details_refreshes_stale_cache(mock_fetch, mock_get_cursor):
    stale = datetime.now(timezone.utc) - timedelta(days=31)
    fresh = datetime.now(timezone.utc)
    cur = FakeCursor([enrichment_row(stale), enrichment_row(fresh)])
    mock_get_cursor.side_effect = lambda: fake_get_cursor(cur)

    resp = client.get("/api/books/B002V5GO3O/details")

    assert resp.status_code == 200
    assert resp.json()["stale"] is False
    mock_fetch.assert_called_once_with(1, 42, "B002V5GO3O")


@patch("audiblimey.api.routes.enrichment.get_cursor")
@patch("audiblimey.api.routes.enrichment._fetch_and_store")
def test_get_details_returns_cached_payload_when_audible_fails(mock_fetch, mock_get_cursor):
    stale = datetime.now(timezone.utc) - timedelta(days=31)
    cur = FakeCursor([enrichment_row(stale)])
    mock_get_cursor.side_effect = lambda: fake_get_cursor(cur)
    mock_fetch.side_effect = RuntimeError("No Audible account configured for user")

    resp = client.get("/api/books/B002V5GO3O/details")

    assert resp.status_code == 200
    data = resp.json()
    assert data["stale"] is True
    assert "No Audible account" in data["error"]
    assert data["full_description"] == "<p>Full description</p>"


@patch("audiblimey.api.routes.enrichment.get_cursor")
@patch("audiblimey.api.routes.enrichment._fetch_and_store")
def test_get_details_returns_404_for_unknown_asin(mock_fetch, mock_get_cursor):
    cur = FakeCursor([])
    mock_get_cursor.side_effect = lambda: fake_get_cursor(cur)

    resp = client.get("/api/books/UNKNOWN/details")

    assert resp.status_code == 404
    mock_fetch.assert_not_called()


@patch("audiblimey.api.routes.enrichment.get_cursor")
@patch("audiblimey.api.routes.enrichment._fetch_and_store")
def test_post_refresh_details_forces_fetch(mock_fetch, mock_get_cursor):
    fresh = datetime.now(timezone.utc)
    cur = FakeCursor([enrichment_row(fresh), enrichment_row(fresh)])
    mock_get_cursor.side_effect = lambda: fake_get_cursor(cur)

    resp = client.post("/api/books/B002V5GO3O/refresh-details")

    assert resp.status_code == 200
    assert resp.json()["stale"] is False
    mock_fetch.assert_called_once_with(1, 42, "B002V5GO3O")
