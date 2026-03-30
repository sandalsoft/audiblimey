"""Tests for the search API endpoint."""

from contextlib import contextmanager
from unittest.mock import patch, MagicMock

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


def _make_fake_client(embedding=None):
    """Create a mock OpenAI client that returns a fixed embedding."""
    if embedding is None:
        embedding = [0.1] * 1536

    mock_client = MagicMock()
    mock_item = MagicMock()
    mock_item.index = 0
    mock_item.embedding = embedding
    mock_response = MagicMock()
    mock_response.data = [mock_item]
    mock_client.embeddings.create.return_value = mock_response
    return mock_client


def _standard_search_results():
    """Standard result rows matching the search SQL SELECT columns."""
    return [
        ("B00BOOK001", "Fantasy Epic", "Author A", 720, 0.9215, 4.5, "Fantasy, Fiction"),
        ("B00BOOK002", "Sci-Fi Adventure", "Author B", 480, 0.8734, None, "Science Fiction"),
    ]


class TestSearchEndpoint:
    """Tests for GET /api/search."""

    @patch("audiblimey.api.routes.search.get_cursor")
    @patch("audiblimey.engine.search._get_openai_client")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_basic_search_returns_results(self, mock_get_client, mock_gc):
        mock_get_client.return_value = _make_fake_client()
        cur = FakeCursor({"similarity_score": _standard_search_results()})
        mock_gc.return_value = fake_get_cursor(cur)

        resp = client.get("/api/search?q=fantasy+books")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "fantasy books"
        assert len(data["items"]) == 2
        assert data["items"][0]["asin"] == "B00BOOK001"
        assert data["items"][0]["similarity_score"] == 0.9215
        assert data["items"][0]["runtime_hours"] == 12.0
        assert data["items"][0]["user_rating"] == 4.5
        assert data["items"][0]["categories"] == "Fantasy, Fiction"

    def test_missing_query_returns_422(self):
        """The q parameter is required."""
        resp = client.get("/api/search")
        assert resp.status_code == 422

    def test_empty_query_returns_422(self):
        """Empty string for q should fail validation (min_length=1)."""
        resp = client.get("/api/search?q=")
        assert resp.status_code == 422

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_api_key_returns_503(self):
        """Missing OPENAI_API_KEY returns 503 with clear message."""
        import os
        os.environ.pop("OPENAI_API_KEY", None)

        resp = client.get("/api/search?q=test")
        assert resp.status_code == 503
        assert "OPENAI_API_KEY" in resp.json()["detail"]

    @patch("audiblimey.api.routes.search.get_cursor")
    @patch("audiblimey.engine.search._get_openai_client")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_no_results_returns_empty_items(self, mock_get_client, mock_gc):
        mock_get_client.return_value = _make_fake_client()
        cur = FakeCursor({"similarity_score": []})
        mock_gc.return_value = fake_get_cursor(cur)

        resp = client.get("/api/search?q=completely+obscure+topic")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["query"] == "completely obscure topic"

    @patch("audiblimey.api.routes.search.get_cursor")
    @patch("audiblimey.engine.search._get_openai_client")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_with_runtime_filters(self, mock_get_client, mock_gc):
        mock_get_client.return_value = _make_fake_client()
        cur = FakeCursor({"similarity_score": _standard_search_results()})
        mock_gc.return_value = fake_get_cursor(cur)

        resp = client.get("/api/search?q=fantasy&min_runtime=5&max_runtime=15")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2

    @patch("audiblimey.api.routes.search.get_cursor")
    @patch("audiblimey.engine.search._get_openai_client")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_with_rating_filter(self, mock_get_client, mock_gc):
        mock_get_client.return_value = _make_fake_client()
        cur = FakeCursor({"similarity_score": _standard_search_results()})
        mock_gc.return_value = fake_get_cursor(cur)

        resp = client.get("/api/search?q=good+books&min_rating=4")
        assert resp.status_code == 200
        assert resp.json()["items"] is not None

    @patch("audiblimey.api.routes.search.get_cursor")
    @patch("audiblimey.engine.search._get_openai_client")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_custom_limit(self, mock_get_client, mock_gc):
        mock_get_client.return_value = _make_fake_client()
        cur = FakeCursor({"similarity_score": _standard_search_results()})
        mock_gc.return_value = fake_get_cursor(cur)

        resp = client.get("/api/search?q=test&limit=5")
        assert resp.status_code == 200

    def test_limit_validation_too_high(self):
        """Limit above 50 should fail validation."""
        resp = client.get("/api/search?q=test&limit=51")
        assert resp.status_code == 422

    def test_limit_validation_too_low(self):
        """Limit below 1 should fail validation."""
        resp = client.get("/api/search?q=test&limit=0")
        assert resp.status_code == 422

    def test_rating_validation_too_low(self):
        """Rating below 1 should fail validation."""
        resp = client.get("/api/search?q=test&min_rating=0")
        assert resp.status_code == 422

    def test_rating_validation_too_high(self):
        """Rating above 5 should fail validation."""
        resp = client.get("/api/search?q=test&min_rating=6")
        assert resp.status_code == 422

    @patch("audiblimey.api.routes.search.search_books")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_search_engine_error_returns_500(self, mock_search):
        mock_search.side_effect = RuntimeError("Database connection failed")

        resp = client.get("/api/search?q=test")
        assert resp.status_code == 500
        assert "Search failed" in resp.json()["detail"]
