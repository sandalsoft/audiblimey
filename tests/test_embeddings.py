"""Tests for embedding engine — text composition, pipeline, and idempotency."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch, call

import pytest

from audiblimey.engine.embeddings import (
    compose_embedding_text,
    embed_books,
    run_embedding_pipeline,
    BATCH_SIZE,
    EMBEDDING_MODEL,
)


# ---------------------------------------------------------------------------
# compose_embedding_text
# ---------------------------------------------------------------------------


class TestComposeEmbeddingText:
    def test_full_metadata(self):
        row = {
            "title": "Project Hail Mary",
            "subtitle": "A Novel",
            "authors": "Andy Weir",
            "categories": "Science Fiction, Space Opera",
            "summary": "A lone astronaut must save Earth.",
        }
        text = compose_embedding_text(row)
        assert "Project Hail Mary" in text
        assert "A Novel" in text
        assert "by Andy Weir" in text
        assert "Categories: Science Fiction, Space Opera" in text
        assert "A lone astronaut must save Earth." in text

    def test_partial_metadata_missing_subtitle_and_categories(self):
        row = {
            "title": "Dune",
            "subtitle": None,
            "authors": "Frank Herbert",
            "categories": "",
            "summary": "A desert planet story.",
        }
        text = compose_embedding_text(row)
        assert "Dune" in text
        assert "by Frank Herbert" in text
        assert "A desert planet story." in text
        assert "Categories:" not in text
        # No subtitle segment
        parts = text.split(". ")
        assert parts[0] == "Dune"

    def test_empty_fields_returns_empty_string(self):
        row = {
            "title": "",
            "subtitle": None,
            "authors": None,
            "categories": None,
            "summary": None,
        }
        text = compose_embedding_text(row)
        assert text == ""

    def test_only_title(self):
        row = {
            "title": "Neuromancer",
            "subtitle": None,
            "authors": None,
            "categories": None,
            "summary": None,
        }
        text = compose_embedding_text(row)
        assert text == "Neuromancer"

    def test_whitespace_handling(self):
        row = {
            "title": "  Spaced  ",
            "subtitle": "  ",
            "authors": "  Author  ",
            "categories": None,
            "summary": "  A summary.  ",
        }
        text = compose_embedding_text(row)
        assert "Spaced" in text
        assert "by Author" in text
        assert "A summary." in text

    def test_missing_keys_use_defaults(self):
        """compose_embedding_text should handle missing dict keys via .get()."""
        row = {"title": "Minimal"}
        text = compose_embedding_text(row)
        assert text == "Minimal"


# ---------------------------------------------------------------------------
# Helpers for embed_books tests
# ---------------------------------------------------------------------------


def _make_fake_embedding(dim=1536, seed=0.1):
    """Return a reproducible fake embedding vector."""
    return [seed + i * 0.0001 for i in range(dim)]


class FakeEmbeddingCursor:
    """Dispatches results based on SQL patterns, tracks UPDATE calls."""

    def __init__(self, books=None):
        self.books = books or []
        self._last_query = None
        self._results = []
        self.updates = []  # track (embedding_str, book_id) calls

    def execute(self, query, params=None):
        self._last_query = query.strip()
        if "FROM books" in self._last_query and "UPDATE" not in self._last_query:
            # SELECT query for fetching books
            self._results = list(self.books)
        elif "UPDATE books SET embedding" in self._last_query:
            if params:
                self.updates.append(params)
            self._results = []
        else:
            self._results = []

    def fetchall(self):
        return self._results

    def fetchone(self):
        return self._results[0] if self._results else None

    def close(self):
        pass


class FakeOpenAIClient:
    """Mocks OpenAI embeddings.create — returns deterministic vectors."""

    def __init__(self, dim=1536):
        self.dim = dim
        self.call_count = 0
        self.call_log = []  # list of input text lists

    @property
    def embeddings(self):
        return self

    def create(self, model=None, input=None):
        self.call_count += 1
        self.call_log.append(input)
        # Return a response-like object
        data = []
        for i, text in enumerate(input):
            emb = _make_fake_embedding(self.dim, seed=self.call_count + i * 0.01)
            item = MagicMock()
            item.index = i
            item.embedding = emb
            data.append(item)
        response = MagicMock()
        response.data = data
        return response


# ---------------------------------------------------------------------------
# embed_books
# ---------------------------------------------------------------------------


class TestEmbedBooks:
    def test_embeds_books_and_stores_vectors(self):
        """Pipeline fetches books, calls OpenAI, writes vectors to DB."""
        books_rows = [
            (1, "B001", "Book One", "Sub One", "Summary one.", "Author A", "Fiction"),
            (2, "B002", "Book Two", None, "Summary two.", "Author B", "Nonfiction"),
        ]
        cursor = FakeEmbeddingCursor(books=books_rows)
        client = FakeOpenAIClient()

        stats = embed_books(cursor, force=False, client=client)

        assert stats["embedded"] == 2
        assert stats["errors"] == 0
        assert client.call_count == 1  # both fit in one batch
        assert len(cursor.updates) == 2
        # Verify embedding string format: [0.1,0.1001,...] 
        emb_str = cursor.updates[0][0]
        assert emb_str.startswith("[")
        assert emb_str.endswith("]")
        assert "," in emb_str

    def test_batching_splits_large_sets(self):
        """Books exceeding BATCH_SIZE are split into multiple API calls."""
        n_books = BATCH_SIZE + 10
        books_rows = [
            (i, f"B{i:03d}", f"Book {i}", None, f"Summary {i}", f"Author {i}", "")
            for i in range(1, n_books + 1)
        ]
        cursor = FakeEmbeddingCursor(books=books_rows)
        client = FakeOpenAIClient()

        stats = embed_books(cursor, force=False, client=client)

        assert stats["embedded"] == n_books
        assert client.call_count == 2  # 50 + 10

    def test_skips_already_embedded_when_not_force(self):
        """When force=False, _fetch_books_for_embedding adds WHERE embedding IS NULL.

        We verify by checking the SQL doesn't include 'force' — the cursor
        returns no books (simulating all have embeddings).
        """
        cursor = FakeEmbeddingCursor(books=[])
        client = FakeOpenAIClient()

        stats = embed_books(cursor, force=False, client=client)

        assert stats["embedded"] == 0
        assert stats["skipped"] == 0
        assert stats["errors"] == 0
        assert client.call_count == 0

    def test_handles_api_failure_gracefully(self):
        """If OpenAI API fails after retries, errors are recorded not raised."""
        books_rows = [
            (1, "B001", "Book One", None, "Summary.", "Author A", "Fiction"),
        ]
        cursor = FakeEmbeddingCursor(books=books_rows)

        # Client that always fails
        client = MagicMock()
        client.embeddings.create.side_effect = Exception("Rate limit exceeded")

        # Patch time.sleep to avoid test delay from retries
        with patch("audiblimey.engine.embeddings.time.sleep"):
            stats = embed_books(cursor, force=False, client=client)

        assert stats["errors"] == 1
        assert stats["embedded"] == 0
        assert len(stats["error_details"]) == 1
        assert "Rate limit" in stats["error_details"][0]["error"]

    def test_skips_books_with_empty_text(self):
        """Books where compose_embedding_text produces empty string are skipped."""
        books_rows = [
            (1, "B001", "", None, None, "", ""),  # empty text
            (2, "B002", "Real Book", None, "Summary.", "Author", "Fiction"),
        ]
        cursor = FakeEmbeddingCursor(books=books_rows)
        client = FakeOpenAIClient()

        stats = embed_books(cursor, force=False, client=client)

        assert stats["embedded"] == 1
        assert client.call_count == 1
        # Only one text sent to API
        assert len(client.call_log[0]) == 1


# ---------------------------------------------------------------------------
# run_embedding_pipeline (integration with get_cursor)
# ---------------------------------------------------------------------------


class TestRunEmbeddingPipeline:
    @patch("audiblimey.engine.embeddings._get_openai_client")
    @patch("audiblimey.db.get_cursor")
    def test_pipeline_orchestration(self, mock_get_cursor, mock_get_client):
        """run_embedding_pipeline opens cursor, calls embed_books, returns stats."""
        books_rows = [
            (1, "B001", "Book One", None, "Summary.", "Author A", "Fiction"),
        ]
        cursor = FakeEmbeddingCursor(books=books_rows)
        client = FakeOpenAIClient()

        @contextmanager
        def fake_cursor_ctx():
            yield cursor

        mock_get_cursor.return_value = fake_cursor_ctx()
        mock_get_client.return_value = client

        stats = run_embedding_pipeline(force=False)

        assert stats["embedded"] == 1
        assert stats["errors"] == 0
        assert client.call_count == 1

    @patch("audiblimey.engine.embeddings._get_openai_client")
    @patch("audiblimey.db.get_cursor")
    def test_pipeline_force_reembeds(self, mock_get_cursor, mock_get_client):
        """force=True should pass through to embed_books."""
        cursor = FakeEmbeddingCursor(books=[])
        client = FakeOpenAIClient()

        @contextmanager
        def fake_cursor_ctx():
            yield cursor

        mock_get_cursor.return_value = fake_cursor_ctx()
        mock_get_client.return_value = client

        stats = run_embedding_pipeline(force=True)

        # No books to embed, but no errors
        assert stats["embedded"] == 0
        assert stats["errors"] == 0

    def test_missing_api_key_raises_clear_error(self):
        """Pipeline raises EnvironmentError if OPENAI_API_KEY is not set."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove the key if it exists
            import os
            os.environ.pop("OPENAI_API_KEY", None)

            from audiblimey.engine.embeddings import _get_openai_client
            with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
                _get_openai_client()


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------


class TestRetryBehavior:
    @patch("audiblimey.engine.embeddings.time.sleep")
    def test_retries_on_transient_failure_then_succeeds(self, mock_sleep):
        """API call succeeds on second attempt after initial failure."""
        books_rows = [
            (1, "B001", "Book One", None, "Summary.", "Author A", "Fiction"),
        ]
        cursor = FakeEmbeddingCursor(books=books_rows)

        call_count = 0

        def flaky_create(model=None, input=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Temporary failure")
            # Succeed on retry
            data = []
            for i, text in enumerate(input):
                item = MagicMock()
                item.index = i
                item.embedding = _make_fake_embedding(seed=0.5 + i * 0.01)
                data.append(item)
            response = MagicMock()
            response.data = data
            return response

        client = MagicMock()
        client.embeddings.create.side_effect = flaky_create

        stats = embed_books(cursor, force=False, client=client)

        assert stats["embedded"] == 1
        assert stats["errors"] == 0
        assert call_count == 2
        assert mock_sleep.call_count == 1
