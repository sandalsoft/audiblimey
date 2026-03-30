"""Tests for taste profile API routes."""

from contextlib import contextmanager
from datetime import datetime, timezone
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
# GET /api/taste/profile
# ---------------------------------------------------------------------------


class TestGetTasteProfile:
    """Tests for the GET taste profile endpoint."""

    @patch("audiblimey.api.routes.taste.get_cursor")
    def test_returns_stored_profile(self, mock_gc):
        generated_at = datetime(2026, 3, 29, 12, 0, 0, tzinfo=timezone.utc)
        cur = FakeCursor({
            "profile_text, profile_edited": [(
                "You love sci-fi and fantasy.",
                "I actually prefer mystery too.",
                42,
                generated_at,
                True,
            )],
        })
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/taste/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_text"] == "You love sci-fi and fantasy."
        assert data["profile_edited"] == "I actually prefer mystery too."
        assert data["books_included"] == 42
        assert data["generated_at"] == "2026-03-29T12:00:00+00:00"
        assert data["has_vector"] is True

    @patch("audiblimey.api.routes.taste.get_cursor")
    def test_returns_null_fields_when_no_profile(self, mock_gc):
        """No taste_profiles row exists yet — return null defaults."""
        cur = FakeCursor({})  # Empty results for every query
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.get("/api/taste/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_text"] is None
        assert data["profile_edited"] is None
        assert data["books_included"] == 0
        assert data["generated_at"] is None
        assert data["has_vector"] is False


# ---------------------------------------------------------------------------
# POST /api/taste/generate
# ---------------------------------------------------------------------------


class TestGenerateTasteProfile:
    """Tests for the POST taste generate endpoint."""

    @patch("audiblimey.api.routes.taste.get_cursor")
    @patch("audiblimey.api.routes.taste.generate_taste_profile")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_generate_succeeds(self, mock_gen, mock_gc):
        """Successful generation returns profile text and metadata."""
        mock_gen.return_value = "You gravitate toward epic fantasy and hard sci-fi."

        generated_at = datetime(2026, 3, 29, 14, 0, 0, tzinfo=timezone.utc)
        # First call: generate_taste_profile uses the cursor
        # Second call: re-read for books_included/generated_at
        call_count = [0]
        def gc_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                # Cursor for generate_taste_profile (passed to mock, not used)
                return fake_get_cursor(FakeCursor({}))
            else:
                # Cursor for the re-read query
                return fake_get_cursor(FakeCursor({
                    "books_included": [(35, generated_at)],
                }))

        mock_gc.side_effect = gc_side_effect

        resp = client.post("/api/taste/generate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_text"] == "You gravitate toward epic fantasy and hard sci-fi."
        assert data["books_included"] == 35
        assert data["generated_at"] == "2026-03-29T14:00:00+00:00"
        mock_gen.assert_called_once()

    @patch.dict("os.environ", {}, clear=True)
    def test_generate_returns_503_without_api_key(self):
        """Missing OPENAI_API_KEY returns 503."""
        import os
        os.environ.pop("OPENAI_API_KEY", None)

        resp = client.post("/api/taste/generate")
        assert resp.status_code == 503
        assert "OPENAI_API_KEY" in resp.json()["detail"]

    @patch("audiblimey.api.routes.taste.get_cursor")
    @patch("audiblimey.api.routes.taste.generate_taste_profile")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_generate_returns_400_insufficient_data(self, mock_gen, mock_gc):
        """Engine returns None when not enough books — route returns 400."""
        mock_gen.return_value = None
        mock_gc.side_effect = lambda: fake_get_cursor(FakeCursor({}))

        resp = client.post("/api/taste/generate")
        assert resp.status_code == 400
        assert "not enough" in resp.json()["detail"].lower()

    @patch("audiblimey.api.routes.taste.get_cursor")
    @patch("audiblimey.api.routes.taste.generate_taste_profile")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_generate_returns_500_on_engine_error(self, mock_gen, mock_gc):
        """Unexpected engine error returns 500."""
        mock_gen.side_effect = RuntimeError("OpenAI connection failed")
        mock_gc.side_effect = lambda: fake_get_cursor(FakeCursor({}))

        resp = client.post("/api/taste/generate")
        assert resp.status_code == 500
        assert "failed" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# PUT /api/taste/profile
# ---------------------------------------------------------------------------


class TestUpdateTasteProfile:
    """Tests for the PUT taste profile endpoint."""

    @patch("audiblimey.api.routes.taste.get_cursor")
    def test_saves_user_edits(self, mock_gc):
        """PUT with profile_edited saves and returns the edit."""
        updated_at = datetime(2026, 3, 29, 15, 30, 0, tzinfo=timezone.utc)
        cur = FakeCursor({
            "RETURNING": [(
                "My corrected taste profile text.",
                updated_at,
            )],
        })
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.put(
            "/api/taste/profile",
            json={"profile_edited": "My corrected taste profile text."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_edited"] == "My corrected taste profile text."
        assert data["updated_at"] == "2026-03-29T15:30:00+00:00"

    def test_validates_body_requires_profile_edited(self):
        """PUT without profile_edited in body returns 422."""
        resp = client.put("/api/taste/profile", json={})
        assert resp.status_code == 422

        resp = client.put("/api/taste/profile", json={"wrong_field": "text"})
        assert resp.status_code == 422

    @patch("audiblimey.api.routes.taste.get_cursor")
    def test_returns_404_when_no_profile_exists(self, mock_gc):
        """PUT when no taste_profiles row exists returns 404."""
        cur = FakeCursor({})  # UPDATE RETURNING returns nothing
        mock_gc.side_effect = lambda: fake_get_cursor(cur)

        resp = client.put(
            "/api/taste/profile",
            json={"profile_edited": "Some text"},
        )
        assert resp.status_code == 404
        assert "generate one first" in resp.json()["detail"].lower()
