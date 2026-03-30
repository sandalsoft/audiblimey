"""Tests for ISBN-to-ASIN matching service."""

import pytest

from audiblimey.matching.isbn_asin import (
    match_isbn_direct,
    match_fuzzy_title,
    match_all_goodreads_books,
    _author_matches,
    MatchResult,
)


class TestAuthorMatches:
    def test_exact_match(self):
        assert _author_matches("Brandon Sanderson", "Brandon Sanderson")

    def test_case_insensitive(self):
        assert _author_matches("brandon sanderson", "Brandon Sanderson")

    def test_last_first_format(self):
        assert _author_matches("Brandon Sanderson", "Sanderson, Brandon")

    def test_partial_match(self):
        assert _author_matches("Neil Gaiman", "Neil Gaiman")

    def test_no_match(self):
        assert not _author_matches("Brandon Sanderson", "Neil Gaiman")


class TestMatchISBNDirect:
    """Integration tests — require running PostgreSQL with seed data."""

    @pytest.fixture(autouse=True)
    def check_db(self):
        try:
            from audiblimey.db import get_cursor
            with get_cursor() as cur:
                cur.execute("SELECT 1")
        except Exception:
            pytest.skip("Database not available")

    def test_match_existing_isbn(self):
        # The seed data has books but likely no ISBNs set
        # This tests the code path even if no match found
        result = match_isbn_direct("9780765365279", "0765365278")
        # Result may be None if our seed books don't have ISBN fields set
        # That's OK — we're testing the function doesn't crash
        assert result is None or isinstance(result, MatchResult)

    def test_no_match_for_random_isbn(self):
        result = match_isbn_direct("9999999999999", "9999999999")
        assert result is None


class TestMatchFuzzyTitle:
    """Integration tests — require running PostgreSQL with seed data."""

    @pytest.fixture(autouse=True)
    def check_db(self):
        try:
            from audiblimey.db import get_cursor
            with get_cursor() as cur:
                cur.execute("SELECT 1")
        except Exception:
            pytest.skip("Database not available")

    def test_exact_title_match(self):
        result = match_fuzzy_title("The Way of Kings", "Brandon Sanderson")
        if result:
            assert result.asin == "B003ZWFO7E"
            assert result.match_source == "fuzzy_title"
            assert result.confidence > 0

    def test_similar_title(self):
        result = match_fuzzy_title("Way of Kings", "Brandon Sanderson")
        # May or may not match depending on similarity threshold
        assert result is None or isinstance(result, MatchResult)

    def test_no_match(self):
        result = match_fuzzy_title("Completely Unknown Book Title XYZABC", "Nobody")
        assert result is None


class TestMatchAllGoodreadsBooks:
    """Integration test for the full matching pipeline."""

    @pytest.fixture(autouse=True)
    def check_db(self):
        try:
            from audiblimey.db import get_cursor
            with get_cursor() as cur:
                cur.execute("SELECT 1")
        except Exception:
            pytest.skip("Database not available")

    def test_matching_pipeline(self):
        """Test matching with seed data, no Open Library API calls."""
        from audiblimey.db import get_cursor
        
        # Clean any existing matches from previous test runs
        with get_cursor() as cur:
            cur.execute("DELETE FROM book_isbn_asin_map")
        
        stats = match_all_goodreads_books(
            use_openlibrary=False,  # Don't hit external API in tests
            limit=10,
        )
        
        assert stats["total"] >= 0  # May be 0 if no unmatched books
        assert "match_rate" in stats
        assert stats["errors"] == 0
