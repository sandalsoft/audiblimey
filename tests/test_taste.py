"""Tests for taste engine: centroid computation, context building, and LLM profile generation."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from audiblimey.engine.taste import (
    EMBEDDING_DIMS,
    _parse_pgvector,
    compute_taste_vector,
    build_profile_context,
    generate_taste_profile,
)


# ---------------------------------------------------------------------------
# FakeCursor (K008 pattern)
# ---------------------------------------------------------------------------


class FakeCursor:
    """Fake cursor dispatching results by SQL query patterns."""

    def __init__(self, results_map=None):
        self.results_map = results_map or {}
        self._last_query = None
        self._results = []
        self.executed_queries = []

    def execute(self, query, params=None):
        self._last_query = query.strip()
        self.executed_queries.append((self._last_query, params))
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


def _make_embedding_str(values: list[float]) -> str:
    """Create a pgvector-format string from a list of floats."""
    return "[" + ",".join(str(v) for v in values) + "]"


def _make_full_embedding(base_value: float) -> str:
    """Create a full 1536-dim embedding string filled with base_value."""
    return _make_embedding_str([base_value] * EMBEDDING_DIMS)


# ---------------------------------------------------------------------------
# _parse_pgvector
# ---------------------------------------------------------------------------


class TestParsePgvector:
    def test_valid_vector(self):
        result = _parse_pgvector("[0.1,0.2,0.3]")
        assert result == [0.1, 0.2, 0.3]

    def test_empty_string(self):
        assert _parse_pgvector("") is None

    def test_none_input(self):
        assert _parse_pgvector(None) is None

    def test_malformed_string(self):
        assert _parse_pgvector("[not,a,vector]") is None

    def test_whitespace_padding(self):
        result = _parse_pgvector("  [1.0,2.0]  ")
        assert result == [1.0, 2.0]


# ---------------------------------------------------------------------------
# compute_taste_vector
# ---------------------------------------------------------------------------


class TestComputeTasteVector:
    def test_weighted_centroid_two_books(self):
        """Two books with different ratings → verify weighted average math."""
        emb_a = _make_full_embedding(1.0)  # all 1.0
        emb_b = _make_full_embedding(3.0)  # all 3.0

        # book_id, embedding, gr_rating, user_rating, is_finished, pct_complete
        rows = [
            (1, emb_a, 5, None, True, 100),   # goodreads rating 5
            (2, emb_b, 3, None, True, 100),    # goodreads rating 3
        ]
        cursor = FakeCursor({"embedding IS NOT NULL": rows})

        vector, count = compute_taste_vector(cursor, user_id=1)

        assert count == 2
        assert vector is not None
        # Expected: (5*1.0 + 3*3.0) / (5+3) = (5 + 9) / 8 = 1.75
        assert len(vector) == EMBEDDING_DIMS
        assert abs(vector[0] - 1.75) < 1e-9

    def test_mixed_rating_sources(self):
        """Goodreads > audible user_rating > is_finished fallback."""
        emb = _make_full_embedding(1.0)

        rows = [
            # book with goodreads rating 5 (top priority)
            (1, emb, 5, 4, True, 100),
            # book with no goodreads, audible rating 2
            (2, emb, None, 2, True, 100),
            # book with neither, but is_finished → 3.5
            (3, emb, None, None, True, 100),
        ]
        cursor = FakeCursor({"embedding IS NOT NULL": rows})

        vector, count = compute_taste_vector(cursor, user_id=1)

        assert count == 3
        # weights: 5 + 2 + 3.5 = 10.5
        # all embeddings are 1.0, so centroid is 1.0 regardless of weights
        assert abs(vector[0] - 1.0) < 1e-9

    def test_is_finished_false_over_50_percent(self):
        """Not finished but >50% complete → rating 3.0."""
        emb = _make_full_embedding(2.0)
        rows = [
            (1, emb, None, None, False, 75.0),  # >50%, not finished → 3.0
        ]
        cursor = FakeCursor({"embedding IS NOT NULL": rows})

        vector, count = compute_taste_vector(cursor, user_id=1)

        assert count == 1
        assert abs(vector[0] - 2.0) < 1e-9

    def test_no_eligible_books_empty_library(self):
        """No books in user_libraries → (None, 0)."""
        cursor = FakeCursor({"embedding IS NOT NULL": []})

        vector, count = compute_taste_vector(cursor, user_id=1)

        assert vector is None
        assert count == 0

    def test_books_with_no_rating_and_not_started(self):
        """Books with no rating source and <50% complete → skip → (None, 0)."""
        emb = _make_full_embedding(1.0)
        rows = [
            (1, emb, None, None, False, 10.0),  # <50%, not finished → skip
            (2, emb, 0, 0, False, 0.0),          # zero ratings → skip
        ]
        cursor = FakeCursor({"embedding IS NOT NULL": rows})

        vector, count = compute_taste_vector(cursor, user_id=1)

        assert vector is None
        assert count == 0

    def test_malformed_embedding_skipped(self):
        """Malformed embedding string → skip that book, don't crash."""
        good_emb = _make_full_embedding(1.0)
        rows = [
            (1, "not_a_vector", 5, None, True, 100),  # bad embedding
            (2, good_emb, 4, None, True, 100),          # good embedding
        ]
        cursor = FakeCursor({"embedding IS NOT NULL": rows})

        vector, count = compute_taste_vector(cursor, user_id=1)

        assert count == 1
        assert abs(vector[0] - 1.0) < 1e-9

    def test_wrong_dimension_embedding_skipped(self):
        """Embedding with wrong dimensions → skip."""
        short_emb = _make_embedding_str([0.5] * 10)  # only 10 dims
        good_emb = _make_full_embedding(2.0)
        rows = [
            (1, short_emb, 5, None, True, 100),
            (2, good_emb, 3, None, True, 100),
        ]
        cursor = FakeCursor({"embedding IS NOT NULL": rows})

        vector, count = compute_taste_vector(cursor, user_id=1)

        assert count == 1
        assert abs(vector[0] - 2.0) < 1e-9


# ---------------------------------------------------------------------------
# build_profile_context
# ---------------------------------------------------------------------------


class TestBuildProfileContext:
    def _make_context_cursor(
        self,
        top_books=None,
        genres=None,
        runtime_row=None,
        completion_row=None,
    ):
        """Build a FakeCursor for build_profile_context queries.

        Uses distinctive substrings unique to each query to avoid
        cross-matching (e.g., "ORDER BY" appears in multiple queries).
        """
        results = {}

        # Top books query — HAVING is unique to this query
        if top_books is not None:
            results["HAVING"] = top_books
        else:
            results["HAVING"] = [
                ("The Great Book", "Author A", "Fiction, Fantasy", 5, 600),
                ("Another Read", "Author B", "Mystery", 4, 480),
            ]

        # Genre distribution — "GROUP BY c.name" is unique
        if genres is not None:
            results["GROUP BY c.name"] = genres
        else:
            results["GROUP BY c.name"] = [
                ("Fiction", 15),
                ("Fantasy", 10),
                ("Mystery", 5),
            ]

        # Runtime stats — PERCENTILE_CONT is unique
        if runtime_row is not None:
            results["PERCENTILE_CONT"] = runtime_row
        else:
            results["PERCENTILE_CONT"] = [(480.5, 420.0)]

        # Completion stats — "is_finished THEN 1" is unique
        if completion_row is not None:
            results["is_finished THEN 1"] = completion_row
        else:
            results["is_finished THEN 1"] = [(30, 20)]

        return FakeCursor(results)

    def test_returns_expected_keys(self):
        cursor = self._make_context_cursor()
        ctx = build_profile_context(cursor, user_id=1)

        assert "top_books" in ctx
        assert "genre_distribution" in ctx
        assert "avg_runtime" in ctx
        assert "median_runtime" in ctx
        assert "completion_rate" in ctx
        assert "total_books" in ctx
        assert "finished_books" in ctx

    def test_top_books_structure(self):
        cursor = self._make_context_cursor()
        ctx = build_profile_context(cursor, user_id=1)

        assert len(ctx["top_books"]) == 2
        book = ctx["top_books"][0]
        assert book["title"] == "The Great Book"
        assert book["authors"] == "Author A"
        assert book["categories"] == "Fiction, Fantasy"
        assert book["rating"] == 5.0
        assert book["runtime_min"] == 600

    def test_genre_distribution(self):
        cursor = self._make_context_cursor()
        ctx = build_profile_context(cursor, user_id=1)

        assert ctx["genre_distribution"] == {
            "Fiction": 15,
            "Fantasy": 10,
            "Mystery": 5,
        }

    def test_runtime_stats(self):
        cursor = self._make_context_cursor()
        ctx = build_profile_context(cursor, user_id=1)

        assert ctx["avg_runtime"] == 480.5
        assert ctx["median_runtime"] == 420.0

    def test_completion_rate(self):
        cursor = self._make_context_cursor()
        ctx = build_profile_context(cursor, user_id=1)

        assert ctx["total_books"] == 30
        assert ctx["finished_books"] == 20
        assert abs(ctx["completion_rate"] - 0.67) < 0.01

    def test_empty_library_context(self):
        cursor = self._make_context_cursor(
            top_books=[],
            genres=[],
            runtime_row=[(None, None)],
            completion_row=[(0, 0)],
        )
        ctx = build_profile_context(cursor, user_id=1)

        assert ctx["top_books"] == []
        assert ctx["genre_distribution"] == {}
        assert ctx["avg_runtime"] is None
        assert ctx["median_runtime"] is None
        assert ctx["total_books"] == 0
        assert ctx["completion_rate"] == 0.0


# ---------------------------------------------------------------------------
# generate_taste_profile (mocked OpenAI)
# ---------------------------------------------------------------------------


class TestGenerateTasteProfile:
    def _make_mock_client(self, content="You love fantasy and mystery novels."):
        """Build a mock OpenAI client returning a canned response."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = content
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    def _make_full_cursor(self):
        """Cursor that satisfies both compute_taste_vector and build_profile_context queries."""
        emb = _make_full_embedding(1.0)
        results = {
            # build_profile_context: top books (HAVING is unique to this query)
            "HAVING": [
                ("Fantasy Book", "Author X", "Fantasy", 5, 600),
                ("Mystery Book", "Author Y", "Mystery", 4, 480),
            ],
            # compute_taste_vector query — use "embedding IS NOT NULL" which is
            # unique to the centroid query (not in the top-books query)
            "embedding IS NOT NULL": [
                (1, emb, 5, None, True, 100),
                (2, emb, 4, None, True, 100),
            ],
            # Genre distribution
            "GROUP BY c.name": [
                ("Fantasy", 10),
                ("Mystery", 5),
            ],
            # Runtime stats
            "PERCENTILE_CONT": [(540.0, 500.0)],
            # Completion stats
            "is_finished THEN 1": [(20, 15)],
            # INSERT/upsert (no result needed)
            "INSERT INTO taste_profiles": [],
        }
        return FakeCursor(results)

    def test_generates_and_stores_profile(self):
        """Full flow: compute vector → build context → call LLM → upsert."""
        cursor = self._make_full_cursor()
        mock_client = self._make_mock_client("You love fantasy and mystery novels.")

        result = generate_taste_profile(cursor, user_id=1, client=mock_client)

        assert result == "You love fantasy and mystery novels."
        # Verify LLM was called
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"
        # Verify the prompt includes book titles
        messages = call_kwargs["messages"]
        assert any("Fantasy Book" in m["content"] for m in messages)
        assert any("Mystery Book" in m["content"] for m in messages)
        # Verify upsert was executed
        upsert_queries = [
            q for q, _p in cursor.executed_queries
            if "INSERT INTO taste_profiles" in q
        ]
        assert len(upsert_queries) == 1

    def test_no_eligible_books_returns_none(self):
        """No books with embeddings → returns None without calling LLM."""
        cursor = FakeCursor({"embedding IS NOT NULL": []})
        mock_client = self._make_mock_client()

        result = generate_taste_profile(cursor, user_id=1, client=mock_client)

        assert result is None
        mock_client.chat.completions.create.assert_not_called()

    def test_malformed_openai_response_raises(self):
        """Empty choices from OpenAI → ValueError."""
        cursor = self._make_full_cursor()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = []
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(ValueError, match="missing expected content"):
            generate_taste_profile(cursor, user_id=1, client=mock_client)

    def test_prompt_includes_genre_stats(self):
        """The LLM prompt should include genre distribution, not raw vectors."""
        cursor = self._make_full_cursor()
        mock_client = self._make_mock_client()

        generate_taste_profile(cursor, user_id=1, client=mock_client)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "Fantasy" in user_msg["content"]
        assert "Mystery" in user_msg["content"]
        # Should NOT contain raw embedding numbers
        assert "[0." not in user_msg["content"]

    def test_client_injection_pattern(self):
        """When client is provided, _get_openai_client is not called."""
        cursor = self._make_full_cursor()
        mock_client = self._make_mock_client()

        with patch("audiblimey.engine.taste._get_openai_client") as mock_get:
            generate_taste_profile(cursor, user_id=1, client=mock_client)
            mock_get.assert_not_called()
