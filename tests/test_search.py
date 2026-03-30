"""Tests for the search engine function."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from audiblimey.engine.search import SearchFilters, search_books


class FakeCursor:
    """A fake cursor that returns pre-configured results per query pattern."""

    def __init__(self, results_map=None):
        self.results_map = results_map or {}
        self._last_query = None
        self._results = []
        self.executed_queries = []
        self.executed_params = []

    def execute(self, query, params=None):
        self._last_query = query.strip()
        self.executed_queries.append(self._last_query)
        self.executed_params.append(params)
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


def _make_fake_client(embedding=None):
    """Create a mock OpenAI client that returns a fixed embedding."""
    if embedding is None:
        embedding = [0.1] * 1536

    client = MagicMock()
    mock_item = MagicMock()
    mock_item.index = 0
    mock_item.embedding = embedding
    mock_response = MagicMock()
    mock_response.data = [mock_item]
    client.embeddings.create.return_value = mock_response
    return client


class TestSearchBooks:
    """Tests for the search_books engine function."""

    def _standard_results(self):
        """Standard search result rows matching the SQL SELECT columns."""
        return [
            ("B00BOOK001", "Fantasy Epic", "Author A", 720, 0.9215, 4.5, "Fantasy, Fiction"),
            ("B00BOOK002", "Sci-Fi Adventure", "Author B", 480, 0.8734, None, "Science Fiction"),
            ("B00BOOK003", "Mystery Novel", "Author C", 360, 0.7610, 3.0, "Mystery"),
        ]

    def test_basic_search_returns_ranked_results(self):
        results_map = {"similarity_score": self._standard_results()}
        cursor = FakeCursor(results_map)
        client = _make_fake_client()

        results = search_books(cursor, query="epic fantasy books", client=client)

        assert len(results) == 3
        assert results[0]["asin"] == "B00BOOK001"
        assert results[0]["title"] == "Fantasy Epic"
        assert results[0]["authors"] == "Author A"
        assert results[0]["runtime_hours"] == 12.0
        assert results[0]["similarity_score"] == 0.9215
        assert results[0]["user_rating"] == 4.5
        assert results[0]["categories"] == "Fantasy, Fiction"

        # Verify OpenAI was called with the query text
        client.embeddings.create.assert_called_once()
        call_args = client.embeddings.create.call_args
        assert call_args.kwargs["input"] == ["epic fantasy books"]
        assert call_args.kwargs["model"] == "text-embedding-3-small"

    def test_search_with_no_results(self):
        cursor = FakeCursor({"similarity_score": []})
        client = _make_fake_client()

        results = search_books(cursor, query="nonexistent topic", client=client)
        assert results == []

    def test_limit_capped_at_50(self):
        cursor = FakeCursor({"similarity_score": self._standard_results()})
        client = _make_fake_client()

        search_books(cursor, query="test", limit=100, client=client)

        # Check the LIMIT param in the executed SQL params (last param)
        last_params = cursor.executed_params[-1]
        assert last_params[-1] == 50  # capped from 100 to 50

    def test_runtime_filter_converts_hours_to_minutes(self):
        cursor = FakeCursor({"similarity_score": self._standard_results()})
        client = _make_fake_client()

        filters = SearchFilters(min_runtime_hours=5.0, max_runtime_hours=10.0)
        search_books(cursor, query="long books", filters=filters, client=client)

        # Check the executed SQL contains runtime filter clauses
        sql = cursor.executed_queries[-1]
        assert "runtime_length_min >= %s" in sql
        assert "runtime_length_min <= %s" in sql

        # Check params include converted minutes: 5h=300min, 10h=600min
        params = cursor.executed_params[-1]
        # params order: embedding, min_runtime_min, max_runtime_min, embedding, limit
        assert 300 in params  # 5 hours * 60
        assert 600 in params  # 10 hours * 60

    def test_rating_filter_joins_user_libraries(self):
        cursor = FakeCursor({"similarity_score": self._standard_results()})
        client = _make_fake_client()

        filters = SearchFilters(min_rating=4.0)
        search_books(cursor, query="highly rated", filters=filters, client=client)

        sql = cursor.executed_queries[-1]
        assert "ul.user_rating >= %s" in sql
        assert "user_libraries" in sql

    def test_null_runtime_returns_none_hours(self):
        """Books with NULL runtime_length_min should have runtime_hours=None."""
        results_map = {
            "similarity_score": [
                ("B00NULL", "No Runtime Book", "Author X", None, 0.85, None, "Fiction"),
            ]
        }
        cursor = FakeCursor(results_map)
        client = _make_fake_client()

        results = search_books(cursor, query="any", client=client)
        assert results[0]["runtime_hours"] is None

    def test_openai_error_propagates(self):
        cursor = FakeCursor({})
        client = _make_fake_client()
        client.embeddings.create.side_effect = RuntimeError("API down")

        with pytest.raises(RuntimeError, match="API down"):
            search_books(cursor, query="test", client=client)

    def test_missing_api_key_raises_environment_error(self):
        cursor = FakeCursor({})

        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("OPENAI_API_KEY", None)

            with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
                search_books(cursor, query="test")  # no client passed

    def test_combined_filters(self):
        """All filters can be used together."""
        cursor = FakeCursor({"similarity_score": self._standard_results()})
        client = _make_fake_client()

        filters = SearchFilters(
            min_runtime_hours=2.0,
            max_runtime_hours=8.0,
            min_rating=3.5,
        )
        search_books(cursor, query="test", filters=filters, client=client)

        sql = cursor.executed_queries[-1]
        assert "runtime_length_min >= %s" in sql
        assert "runtime_length_min <= %s" in sql
        assert "ul.user_rating >= %s" in sql
