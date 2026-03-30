"""Tests for embedding and similarity API routes."""

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


# ---------------------------------------------------------------------------
# GET /api/books/{asin}/similar
# ---------------------------------------------------------------------------


class TestGetSimilarBooks:
    """Tests for the similar books endpoint."""

    def _make_cursor_map(self, book_row=None, similar_rows=None):
        """Build FakeCursor results for the similar-books endpoint.

        The endpoint makes two queries:
        1. SELECT id, embedding FROM books WHERE asin = %s
        2. SELECT b.asin, b.title, ... 1 - (b.embedding <=> ...) ...
        """
        results = {}
        # First query: source book lookup
        if book_row is not None:
            results["id, embedding"] = book_row
        else:
            # Default: book exists with an embedding
            results["id, embedding"] = [(1, "[0.1,0.2,0.3]")]

        # Second query: similar books
        if similar_rows is not None:
            results["similarity_score"] = similar_rows
        else:
            results["similarity_score"] = [
                ("B00SIM001", "Similar Book 1", "Author A", 360, 0.9512),
                ("B00SIM002", "Similar Book 2", "Author B", 480, 0.8734),
                ("B00SIM003", "Similar Book 3", "Author C", 240, 0.7921),
            ]

        return FakeCursor(results)

    @patch("audiblimey.api.routes.embeddings.get_cursor")
    def test_similar_books_returns_ranked_results(self, mock_gc):
        cur = self._make_cursor_map()
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/books/B00TEST123/similar")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 3
        # Check ranking order preserved
        assert data["items"][0]["asin"] == "B00SIM001"
        assert data["items"][0]["similarity_score"] == 0.9512
        assert data["items"][0]["title"] == "Similar Book 1"
        assert data["items"][0]["authors"] == "Author A"
        assert data["items"][0]["runtime_hours"] == 6.0
        # Second result
        assert data["items"][1]["similarity_score"] == 0.8734

    @patch("audiblimey.api.routes.embeddings.get_cursor")
    def test_similar_books_custom_limit(self, mock_gc):
        cur = self._make_cursor_map()
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/books/B00TEST123/similar?limit=10")
        assert resp.status_code == 200
        # Still returns 3 (that's all we mocked), but limit param is accepted
        data = resp.json()
        assert len(data["items"]) == 3

    @patch("audiblimey.api.routes.embeddings.get_cursor")
    def test_similar_books_no_embedding_returns_empty(self, mock_gc):
        """Book exists but has no embedding — return empty items, not an error."""
        cur = self._make_cursor_map(book_row=[(1, None)])
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/books/B00NOEMBED/similar")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []

    @patch("audiblimey.api.routes.embeddings.get_cursor")
    def test_similar_books_unknown_asin_returns_404(self, mock_gc):
        """Book doesn't exist at all — return 404."""
        cur = self._make_cursor_map(book_row=[])
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/books/NONEXISTENT/similar")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_similar_books_limit_validation(self):
        """Limit must be between 1 and 20."""
        resp = client.get("/api/books/B00TEST/similar?limit=0")
        assert resp.status_code == 422

        resp = client.get("/api/books/B00TEST/similar?limit=21")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/embeddings/generate
# ---------------------------------------------------------------------------


class TestGenerateEmbeddings:
    """Tests for the embedding generation endpoint."""

    @patch("audiblimey.api.routes.embeddings.run_embedding_pipeline")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_generate_triggers_pipeline(self, mock_pipeline):
        mock_pipeline.return_value = {
            "embedded": 10,
            "skipped": 2,
            "errors": 0,
            "error_details": [],
        }

        resp = client.post("/api/embeddings/generate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["embedded"] == 10
        assert data["skipped"] == 2
        assert data["errors"] == 0
        mock_pipeline.assert_called_once_with(force=False)

    @patch("audiblimey.api.routes.embeddings.run_embedding_pipeline")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_generate_with_force_flag(self, mock_pipeline):
        mock_pipeline.return_value = {
            "embedded": 50,
            "skipped": 0,
            "errors": 0,
            "error_details": [],
        }

        resp = client.post("/api/embeddings/generate", json={"force": True})
        assert resp.status_code == 200
        mock_pipeline.assert_called_once_with(force=True)

    @patch.dict("os.environ", {}, clear=True)
    def test_generate_without_api_key_returns_503(self):
        """Missing OPENAI_API_KEY should return 503 with clear message."""
        # Ensure the key is not set
        import os
        os.environ.pop("OPENAI_API_KEY", None)

        resp = client.post("/api/embeddings/generate")
        assert resp.status_code == 503
        assert "OPENAI_API_KEY" in resp.json()["detail"]

    @patch("audiblimey.api.routes.embeddings.run_embedding_pipeline")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_generate_pipeline_error_returns_500(self, mock_pipeline):
        mock_pipeline.side_effect = RuntimeError("Connection refused")

        resp = client.post("/api/embeddings/generate")
        assert resp.status_code == 500
        assert "pipeline failed" in resp.json()["detail"].lower()
