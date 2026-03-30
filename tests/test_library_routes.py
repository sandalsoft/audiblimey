"""Tests for library API routes."""

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from audiblimey.api.main import app

client = TestClient(app)


class FakeCursor:
    """A fake cursor that returns pre-configured results per query pattern."""

    def __init__(self, results_map=None):
        self.results_map = results_map or {}
        self._last_query = None
        self._results = []

    def execute(self, query, params=None):
        self._last_query = query.strip()
        # Match by first keyword after SELECT
        for pattern, results in self.results_map.items():
            if pattern in self._last_query:
                self._results = list(results)
                return
        self._results = []

    def fetchone(self):
        return self._results[0] if self._results else None

    def fetchall(self):
        return self._results

    def close(self):
        pass


@contextmanager
def fake_get_cursor(cursor):
    """Context manager matching get_cursor interface."""
    yield cursor


# ---------------------------------------------------------------------------
# GET /api/library
# ---------------------------------------------------------------------------


class TestGetLibrary:
    def _mock_cursor(self, count=2, books=None):
        if books is None:
            books = [
                (
                    "B00ABC1234", "Book One", 360,
                    Decimal("75.50"), False, datetime(2024, 1, 15), Decimal("4.5"),
                    "Author A", "Narrator X",
                ),
                (
                    "B00DEF5678", "Book Two", 480,
                    Decimal("0.00"), False, datetime(2024, 2, 20), None,
                    "Author B", "Narrator Y",
                ),
            ]
        results = {
            "COUNT(*)": [(count,)],
            "b.asin, b.title": books,
        }
        return FakeCursor(results)

    @patch("audiblimey.api.routes.library.get_cursor")
    def test_library_returns_paginated_list(self, mock_gc):
        cur = self._mock_cursor()
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/library")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["asin"] == "B00ABC1234"
        assert data["items"][0]["runtime_hours"] == 6.0
        assert data["offset"] == 0
        assert data["limit"] == 20

    @patch("audiblimey.api.routes.library.get_cursor")
    def test_library_with_search(self, mock_gc):
        cur = self._mock_cursor(count=1, books=[
            (
                "B00ABC1234", "Book One", 360,
                Decimal("75.50"), False, datetime(2024, 1, 15), Decimal("4.5"),
                "Author A", "Narrator X",
            ),
        ])
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/library?search=Book")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    @patch("audiblimey.api.routes.library.get_cursor")
    def test_library_offset_beyond_total_returns_empty(self, mock_gc):
        cur = self._mock_cursor(count=2, books=[])
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/library?offset=100")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 2


# ---------------------------------------------------------------------------
# GET /api/books/{asin}
# ---------------------------------------------------------------------------


class TestGetBookDetail:
    def _make_cursor_map(self, book_row=None, authors=None, narrators=None,
                          series=None, price=None, lib_entry=None):
        if book_row is None:
            book_row = [
                (1, "B00TEST123", "Test Book", "A Subtitle", 420,
                 "A great book", "english", "Publisher Inc",
                 date(2023, 6, 1), "Product"),
            ]
        results = {
            "b.id, b.asin, b.title": book_row,
            "a.id, a.asin, a.name": authors or [(1, "A000111", "Test Author")],
            "n.id, n.asin, n.name": narrators or [(1, "N000111", "Test Narrator")],
            "s.id, s.asin, s.title": series or [],
            "member_price, list_price, credit_price": price or [],
            "percent_complete, is_finished, purchase_date": lib_entry or [],
        }
        return FakeCursor(results)

    @patch("audiblimey.api.routes.library.get_cursor")
    def test_book_detail_found(self, mock_gc):
        cur = self._make_cursor_map()
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/books/B00TEST123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asin"] == "B00TEST123"
        assert data["title"] == "Test Book"
        assert data["runtime_hours"] == 7.0
        assert len(data["authors"]) == 1
        assert data["authors"][0]["name"] == "Test Author"
        assert len(data["narrators"]) == 1

    @patch("audiblimey.api.routes.library.get_cursor")
    def test_book_detail_with_price_and_library(self, mock_gc):
        cur = self._make_cursor_map(
            price=[(Decimal("11.95"), Decimal("24.99"), Decimal("1.00"), "USD", date(2024, 3, 1))],
            lib_entry=[(Decimal("50.00"), False, datetime(2024, 1, 1), Decimal("4.0"))],
        )
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/books/B00TEST123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pricing"]["member_price"] == 11.95
        assert data["user_library"]["percent_complete"] == 50.0

    @patch("audiblimey.api.routes.library.get_cursor")
    def test_book_detail_not_found(self, mock_gc):
        cur = self._make_cursor_map(book_row=[])
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/books/NONEXISTENT")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/authors/{id}
# ---------------------------------------------------------------------------


class TestGetAuthorProfile:
    def _make_cursor_map(self, author_row=None, books=None):
        results = {
            "id, asin, name": author_row if author_row is not None else [(1, "A000111", "Test Author")],
            "b.asin, b.title": books or [
                ("B00ABC1234", "Author Book 1", 300, Decimal("100.00"), True, Decimal("5.0")),
                ("B00DEF5678", "Author Book 2", 240, Decimal("50.00"), False, None),
            ],
        }
        return FakeCursor(results)

    @patch("audiblimey.api.routes.library.get_cursor")
    def test_author_profile_found(self, mock_gc):
        cur = self._make_cursor_map()
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/authors/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Author"
        assert data["stats"]["book_count"] == 2
        assert data["stats"]["avg_rating"] == 5.0
        assert data["stats"]["total_runtime_minutes"] == 540

    @patch("audiblimey.api.routes.library.get_cursor")
    def test_author_not_found(self, mock_gc):
        cur = self._make_cursor_map(author_row=[])
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/authors/999999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/narrators/{id}
# ---------------------------------------------------------------------------


class TestGetNarratorProfile:
    def _make_cursor_map(self, narrator_row=None, books=None):
        results = {
            "id, asin, name": narrator_row if narrator_row is not None else [(1, "N000111", "Test Narrator")],
            "b.asin, b.title": books or [
                ("B00ABC1234", "Narrator Book 1", 360, Decimal("80.00"), True, Decimal("4.0")),
            ],
        }
        return FakeCursor(results)

    @patch("audiblimey.api.routes.library.get_cursor")
    def test_narrator_profile_found(self, mock_gc):
        cur = self._make_cursor_map()
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/narrators/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Narrator"
        assert data["stats"]["book_count"] == 1
        assert data["stats"]["avg_rating"] == 4.0
        assert data["stats"]["total_runtime_minutes"] == 360

    @patch("audiblimey.api.routes.library.get_cursor")
    def test_narrator_not_found(self, mock_gc):
        cur = self._make_cursor_map(narrator_row=[])
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/narrators/999999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()
