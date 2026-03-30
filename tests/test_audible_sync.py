"""Tests for Audible sync module and API endpoints."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

from audiblimey.api.main import app
from audiblimey.sync.audible import store_book, _parse_datetime

client = TestClient(app)


# ---------------------------------------------------------------------------
# FakeCursor — records SQL calls for assertion
# ---------------------------------------------------------------------------

class FakeCursor:
    """A recording cursor that returns configurable results per query pattern."""

    def __init__(self, results_map=None):
        self.results_map = results_map or {}
        self._last_query = ""
        self._last_params = None
        self._results = []
        self.executed_queries = []

    def execute(self, query, params=None):
        self._last_query = query.strip()
        self._last_params = params
        self.executed_queries.append((self._last_query, params))
        # Match by substring in query
        for pattern, results in self.results_map.items():
            if pattern in self._last_query:
                if callable(results):
                    self._results = list(results(self._last_query, params))
                else:
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
# store_book unit tests
# ---------------------------------------------------------------------------


class TestStoreBook:
    """Test the store_book function with mocked cursor."""

    def _make_cursor(self, book_id=42):
        """Create a FakeCursor that returns sensible defaults."""
        call_count = {"author": 0, "narrator": 0, "series": 0}

        def dispatch(query, params):
            if "RETURNING id" in query and "INTO books" in query:
                return [(book_id,)]
            if "INTO authors" in query and "RETURNING id" in query:
                call_count["author"] += 1
                return [(100 + call_count["author"],)]
            if "FROM authors WHERE name" in query:
                return []  # not found, triggers insert
            if "INTO narrators" in query and "RETURNING id" in query:
                call_count["narrator"] += 1
                return [(200 + call_count["narrator"],)]
            if "FROM narrators WHERE name" in query:
                return []
            if "INTO series" in query and "RETURNING id" in query:
                call_count["series"] += 1
                return [(300 + call_count["series"],)]
            if "FROM series WHERE title" in query:
                return []
            # Everything else — junction tables, user_libraries
            return []

        return FakeCursor(results_map={"": dispatch})

    def _make_cursor_with_pattern_map(self, results_map):
        """Create a FakeCursor with explicit pattern-based dispatch."""
        return FakeCursor(results_map=results_map)

    def test_store_book_inserts_book_and_relationships(self):
        """Full store_book with authors, narrators, series, user_library."""
        cur = self._make_cursor(book_id=42)

        book_data = {
            "asin": "B00TEST123",
            "title": "Test Audiobook",
            "subtitle": "A Test Subtitle",
            "publisher_name": "Test Publisher",
            "language": "english",
            "runtime_length_min": 360,
            "authors": [{"name": "Author One", "asin": "AUTH001"}],
            "narrators": [{"name": "Narrator One", "asin": "NARR001"}],
            "series": [{"title": "Test Series", "asin": "SER001", "sequence": "1"}],
            "purchase_date": "2024-01-15T00:00:00Z",
            "percent_complete": 50.0,
            "is_finished": False,
        }

        result = store_book(cur, user_id=1, book_data=book_data)

        assert result == 42

        # Verify book upsert was called
        book_queries = [q for q, _ in cur.executed_queries if "INTO books" in q]
        assert len(book_queries) == 1
        assert "ON CONFLICT (asin) DO UPDATE" in book_queries[0]

        # Verify author upsert
        author_queries = [q for q, _ in cur.executed_queries if "INTO authors" in q]
        assert len(author_queries) >= 1

        # Verify narrator upsert
        narrator_queries = [q for q, _ in cur.executed_queries if "INTO narrators" in q]
        assert len(narrator_queries) >= 1

        # Verify series upsert
        series_queries = [q for q, _ in cur.executed_queries if "INTO series" in q]
        assert len(series_queries) >= 1

        # Verify junction tables
        ba_queries = [q for q, _ in cur.executed_queries if "INTO book_authors" in q]
        assert len(ba_queries) == 1

        bn_queries = [q for q, _ in cur.executed_queries if "INTO book_narrators" in q]
        assert len(bn_queries) == 1

        bs_queries = [q for q, _ in cur.executed_queries if "INTO book_series" in q]
        assert len(bs_queries) == 1

        # Verify user_libraries upsert
        ul_queries = [q for q, _ in cur.executed_queries if "INTO user_libraries" in q]
        assert len(ul_queries) == 1

    def test_store_book_skips_missing_asin(self):
        """Book with no ASIN should be skipped — return None."""
        cur = self._make_cursor()

        book_data = {"title": "No ASIN Book", "authors": [{"name": "Someone"}]}
        result = store_book(cur, user_id=1, book_data=book_data)

        assert result is None
        # No SQL should have been executed
        assert len(cur.executed_queries) == 0

    def test_store_book_skips_empty_title(self):
        """Book with ASIN but empty title should be skipped."""
        cur = self._make_cursor()

        book_data = {"asin": "B00NOTITLE", "title": ""}
        result = store_book(cur, user_id=1, book_data=book_data)

        assert result is None
        assert len(cur.executed_queries) == 0

    def test_store_book_handles_empty_authors(self):
        """Book with no authors should still be stored, just without author links."""
        cur = self._make_cursor(book_id=55)

        book_data = {
            "asin": "B00NOAUTH",
            "title": "No Authors",
            "authors": [],
            "narrators": [],
            "series": [],
        }
        result = store_book(cur, user_id=1, book_data=book_data)

        assert result == 55

        # Should have book upsert and user_libraries — no author/narrator/series
        author_queries = [q for q, _ in cur.executed_queries if "INTO authors" in q or "FROM authors" in q]
        assert len(author_queries) == 0

        narrator_queries = [q for q, _ in cur.executed_queries if "INTO narrators" in q or "FROM narrators" in q]
        assert len(narrator_queries) == 0

    def test_store_book_handles_none_authors_narrators_series(self):
        """Book with None for relationship lists should be handled gracefully."""
        cur = self._make_cursor(book_id=66)

        book_data = {
            "asin": "B00NONELISTS",
            "title": "None Lists",
            "authors": None,
            "narrators": None,
            "series": None,
        }
        result = store_book(cur, user_id=1, book_data=book_data)

        assert result == 66

    def test_store_book_author_without_asin_dedup(self):
        """Author without ASIN should be looked up by name, inserted if new."""
        # Simulate: first SELECT returns nothing (new author), then INSERT returns id
        call_state = {"phase": "lookup"}

        def dispatch(query, params):
            if "INTO books" in query and "RETURNING id" in query:
                return [(42,)]
            if "FROM authors WHERE name" in query:
                return []  # not found
            if "INTO authors" in query and "RETURNING id" in query:
                return [(101,)]
            return []

        cur = FakeCursor(results_map={"": dispatch})

        book_data = {
            "asin": "B00NOASINAUTH",
            "title": "Author No ASIN",
            "authors": [{"name": "No ASIN Author"}],
        }
        result = store_book(cur, user_id=1, book_data=book_data)
        assert result == 42

        # Verify the lookup-then-insert pattern
        name_lookups = [q for q, _ in cur.executed_queries if "FROM authors WHERE name" in q]
        assert len(name_lookups) == 1
        inserts = [q for q, _ in cur.executed_queries if "INTO authors" in q and "RETURNING" in q]
        assert len(inserts) >= 1


# ---------------------------------------------------------------------------
# _parse_datetime
# ---------------------------------------------------------------------------


class TestParseDatetime:
    def test_iso_with_z(self):
        result = _parse_datetime("2024-01-15T12:00:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1

    def test_iso_without_z(self):
        result = _parse_datetime("2024-06-01T10:30:00")
        assert result is not None

    def test_none_input(self):
        assert _parse_datetime(None) is None

    def test_invalid_string(self):
        assert _parse_datetime("not-a-date") is None

    def test_empty_string(self):
        assert _parse_datetime("") is None


# ---------------------------------------------------------------------------
# POST /api/sync/audible endpoint tests
# ---------------------------------------------------------------------------


class TestSyncEndpoint:
    @patch("audiblimey.api.routes.sync.get_cursor")
    def test_sync_returns_400_when_no_account(self, mock_gc):
        """POST /api/sync/audible with no user_audible_accounts row → 400."""
        cur = FakeCursor(results_map={
            "FROM user_audible_accounts": [],
        })
        mock_gc.side_effect = lambda **kw: fake_get_cursor(cur)

        resp = client.post("/api/sync/audible")
        assert resp.status_code == 400
        assert "No Audible account" in resp.json()["detail"]

    @patch("audiblimey.api.routes.sync.run_sync")
    @patch("audiblimey.api.routes.sync.get_cursor")
    def test_sync_returns_409_when_already_running(self, mock_gc, mock_run):
        """POST /api/sync/audible when sync is running → 409."""
        call_count = {"n": 0}

        def make_cursor(**kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: check for audible account → found
                return fake_get_cursor(FakeCursor(results_map={
                    "FROM user_audible_accounts": [(1,)],
                }))
            else:
                # Second call: check for running job → found
                return fake_get_cursor(FakeCursor(results_map={
                    "FROM sync_jobs": [(99,)],
                }))

        mock_gc.side_effect = make_cursor

        resp = client.post("/api/sync/audible")
        assert resp.status_code == 409
        assert "already running" in resp.json()["detail"]

    @patch("audiblimey.api.routes.sync.run_sync")
    @patch("audiblimey.api.routes.sync.get_cursor")
    def test_sync_starts_successfully(self, mock_gc, mock_run):
        """POST /api/sync/audible with account and no running job → starts sync."""
        call_count = {"n": 0}

        def make_cursor(**kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Check for audible account → found
                return fake_get_cursor(FakeCursor(results_map={
                    "FROM user_audible_accounts": [(1,)],
                }))
            elif call_count["n"] == 2:
                # Check for running job → none
                return fake_get_cursor(FakeCursor(results_map={
                    "FROM sync_jobs": [],
                }))
            else:
                # Create sync job → return job_id
                return fake_get_cursor(FakeCursor(results_map={
                    "RETURNING id": [(77,)],
                }))

        mock_gc.side_effect = make_cursor

        resp = client.post("/api/sync/audible")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == 77
        assert data["status"] == "started"

    @patch("audiblimey.api.routes.sync.run_sync")
    @patch("audiblimey.api.routes.sync.get_cursor")
    def test_sync_empty_library_completes(self, mock_gc, mock_run):
        """Sync with an empty library should complete successfully (0 books)."""
        call_count = {"n": 0}

        def make_cursor(**kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return fake_get_cursor(FakeCursor(results_map={
                    "FROM user_audible_accounts": [(1,)],
                }))
            elif call_count["n"] == 2:
                return fake_get_cursor(FakeCursor(results_map={
                    "FROM sync_jobs": [],
                }))
            else:
                return fake_get_cursor(FakeCursor(results_map={
                    "RETURNING id": [(88,)],
                }))

        mock_gc.side_effect = make_cursor

        resp = client.post("/api/sync/audible")
        assert resp.status_code == 200
        # The actual sync runs in background — we just verify the endpoint accepted it
        assert resp.json()["status"] == "started"


# ---------------------------------------------------------------------------
# GET /api/sync/status
# ---------------------------------------------------------------------------


class TestSyncStatusEndpoint:
    @patch("audiblimey.api.routes.sync.get_cursor")
    def test_status_no_syncs(self, mock_gc):
        """GET /api/sync/status when no jobs exist."""
        cur = FakeCursor(results_map={})
        mock_gc.side_effect = lambda **kw: fake_get_cursor(cur)

        resp = client.get("/api/sync/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_syncs"

    @patch("audiblimey.api.routes.sync.get_cursor")
    def test_status_returns_latest_job(self, mock_gc):
        """GET /api/sync/status returns the latest sync job."""
        from datetime import datetime
        cur = FakeCursor(results_map={
            "FROM sync_jobs": [(
                5, "library_sync", "completed",
                datetime(2024, 3, 1, 10, 0), datetime(2024, 3, 1, 10, 5),
                150, 140, 10, None, datetime(2024, 3, 1, 9, 59),
            )],
        })
        mock_gc.side_effect = lambda **kw: fake_get_cursor(cur)

        resp = client.get("/api/sync/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == 5
        assert data["status"] == "completed"
        assert data["books_processed"] == 150
