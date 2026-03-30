"""Tests for Goodreads CSV parser."""

import csv
import os
import tempfile
from pathlib import Path

import pytest

from audiblimey.importers.goodreads import (
    GoodreadsBook,
    classify_shelves,
    parse_csv,
    import_to_db,
    _clean_isbn,
    _parse_date,
    NEGATIVE_SHELVES,
    POSITIVE_SHELVES,
)


# --- Fixtures ---

SAMPLE_CSV_HEADER = [
    "Book Id", "Title", "Author", "Author l-f", "Additional Authors",
    "ISBN", "ISBN13", "My Rating", "Average Rating", "Publisher",
    "Binding", "Number of Pages", "Year Published", "Original Publication Year",
    "Date Read", "Date Added", "Bookshelves", "Bookshelves with positions",
    "Exclusive Shelf", "My Review", "Spoiler", "Private Notes",
    "Read Count", "Owned Copies",
]

SAMPLE_ROWS = [
    {
        "Book Id": "7235533",
        "Title": "The Way of Kings (The Stormlight Archive, #1)",
        "Author": "Brandon Sanderson",
        "Author l-f": "Sanderson, Brandon",
        "Additional Authors": "",
        "ISBN": '="0765365278"',
        "ISBN13": '="9780765365279"',
        "My Rating": "5",
        "Average Rating": "4.64",
        "Publisher": "Tor Books",
        "Binding": "Hardcover",
        "Number of Pages": "1007",
        "Year Published": "2010",
        "Original Publication Year": "2010",
        "Date Read": "2023/01/20",
        "Date Added": "2022/12/01",
        "Bookshelves": "favorites, fantasy, epic",
        "Bookshelves with positions": "favorites (#1), fantasy (#5), epic (#3)",
        "Exclusive Shelf": "read",
        "My Review": "Incredible worldbuilding and magic system.",
        "Spoiler": "",
        "Private Notes": "",
        "Read Count": "2",
        "Owned Copies": "1",
    },
    {
        "Book Id": "18007564",
        "Title": "The Martian",
        "Author": "Andy Weir",
        "Author l-f": "Weir, Andy",
        "Additional Authors": "",
        "ISBN": '="0553418025"',
        "ISBN13": '="9780553418026"',
        "My Rating": "4",
        "Average Rating": "4.40",
        "Publisher": "Crown",
        "Binding": "Hardcover",
        "Number of Pages": "369",
        "Year Published": "2014",
        "Original Publication Year": "2011",
        "Date Read": "2023/03/25",
        "Date Added": "2023/02/15",
        "Bookshelves": "sci-fi, favorites",
        "Bookshelves with positions": "sci-fi (#2), favorites (#4)",
        "Exclusive Shelf": "read",
        "My Review": "",
        "Spoiler": "",
        "Private Notes": "",
        "Read Count": "1",
        "Owned Copies": "0",
    },
    {
        "Book Id": "30165203",
        "Title": "A Terrible Book",
        "Author": "Bad Author",
        "Author l-f": "Author, Bad",
        "Additional Authors": "",
        "ISBN": "",
        "ISBN13": "",
        "My Rating": "1",
        "Average Rating": "3.20",
        "Publisher": "SomePress",
        "Binding": "Paperback",
        "Number of Pages": "200",
        "Year Published": "2020",
        "Original Publication Year": "2020",
        "Date Read": "2023/02/10",
        "Date Added": "2023/01/30",
        "Bookshelves": "abandoned, dnf",
        "Bookshelves with positions": "abandoned (#1), dnf (#1)",
        "Exclusive Shelf": "read",
        "My Review": "",
        "Spoiler": "",
        "Private Notes": "",
        "Read Count": "0",
        "Owned Copies": "0",
    },
    {
        "Book Id": "12345",
        "Title": "Unrated TBR Book",
        "Author": "Future Author",
        "Author l-f": "Author, Future",
        "Additional Authors": "Co Author",
        "ISBN": '="1234567890"',
        "ISBN13": '="9781234567890"',
        "My Rating": "0",
        "Average Rating": "4.10",
        "Publisher": "Publisher",
        "Binding": "Kindle",
        "Number of Pages": "",
        "Year Published": "2025",
        "Original Publication Year": "",
        "Date Read": "",
        "Date Added": "2024/01/01",
        "Bookshelves": "",
        "Bookshelves with positions": "",
        "Exclusive Shelf": "to-read",
        "My Review": "",
        "Spoiler": "",
        "Private Notes": "",
        "Read Count": "0",
        "Owned Copies": "0",
    },
]


@pytest.fixture
def sample_csv(tmp_path):
    """Create a sample Goodreads CSV file."""
    csv_file = tmp_path / "goodreads_export.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SAMPLE_CSV_HEADER)
        writer.writeheader()
        for row in SAMPLE_ROWS:
            writer.writerow(row)
    return csv_file


# --- Unit Tests ---

class TestCleanISBN:
    def test_strips_equals_and_quotes(self):
        assert _clean_isbn('="9780765365279"') == "9780765365279"

    def test_handles_empty(self):
        assert _clean_isbn("") == ""
        assert _clean_isbn(None) == ""

    def test_handles_plain_isbn(self):
        assert _clean_isbn("9780765365279") == "9780765365279"


class TestParseDate:
    def test_slash_format(self):
        assert _parse_date("2023/01/20") == __import__("datetime").date(2023, 1, 20)

    def test_dash_format(self):
        assert _parse_date("2023-01-20") == __import__("datetime").date(2023, 1, 20)

    def test_empty(self):
        assert _parse_date("") is None
        assert _parse_date(None) is None

    def test_invalid(self):
        assert _parse_date("not-a-date") is None


class TestClassifyShelves:
    def test_negative_shelves(self):
        _, _, negative, _ = classify_shelves("abandoned, dnf")
        assert "abandoned" in negative
        assert "dnf" in negative

    def test_positive_shelves(self):
        _, positive, _, _ = classify_shelves("favorites, loved")
        assert "favorites" in positive
        assert "loved" in positive

    def test_genre_shelves(self):
        _, _, _, genre = classify_shelves("favorites, sci-fi, fantasy, to-read")
        assert "sci-fi" in genre
        assert "fantasy" in genre
        assert "favorites" not in genre
        assert "to-read" not in genre

    def test_empty(self):
        all_s, pos, neg, genre = classify_shelves("")
        assert all_s == []
        assert pos == []
        assert neg == []
        assert genre == []

    def test_mixed(self):
        all_s, pos, neg, genre = classify_shelves("favorites, abandoned, mystery, to-read")
        assert len(all_s) == 4
        assert pos == ["favorites"]
        assert neg == ["abandoned"]
        assert genre == ["mystery"]


class TestParseCSV:
    def test_parses_all_rows(self, sample_csv):
        books = parse_csv(sample_csv)
        assert len(books) == 4

    def test_first_book_fields(self, sample_csv):
        books = parse_csv(sample_csv)
        book = books[0]
        assert book.goodreads_book_id == "7235533"
        assert book.title == "The Way of Kings (The Stormlight Archive, #1)"
        assert book.author == "Brandon Sanderson"
        assert book.isbn13 == "9780765365279"
        assert book.my_rating == 5
        assert book.average_rating == 4.64
        assert book.num_pages == 1007
        assert book.date_read is not None
        assert book.my_review == "Incredible worldbuilding and magic system."

    def test_shelf_classification(self, sample_csv):
        books = parse_csv(sample_csv)
        
        # Book 1: favorites + genre
        assert "favorites" in books[0].positive_shelves
        assert "fantasy" in books[0].genre_shelves
        assert "epic" in books[0].genre_shelves
        
        # Book 3: abandoned
        assert "abandoned" in books[2].negative_shelves
        assert "dnf" in books[2].negative_shelves

    def test_missing_isbn_handled(self, sample_csv):
        books = parse_csv(sample_csv)
        # Book 3 has empty ISBN
        assert books[2].isbn == ""
        assert books[2].isbn13 == ""

    def test_unrated_book(self, sample_csv):
        books = parse_csv(sample_csv)
        assert books[3].my_rating == 0
        assert books[3].exclusive_shelf == "to-read"
        assert books[3].date_read is None

    def test_additional_authors(self, sample_csv):
        books = parse_csv(sample_csv)
        assert books[3].additional_authors == "Co Author"

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_csv("/nonexistent/file.csv")


class TestImportToDB:
    """Integration tests — require running PostgreSQL."""

    @pytest.fixture(autouse=True)
    def check_db(self):
        """Skip if database is not available."""
        try:
            from audiblimey.db import get_cursor
            with get_cursor() as cur:
                cur.execute("SELECT 1")
        except Exception:
            pytest.skip("Database not available")

    def test_import_and_stats(self, sample_csv):
        books = parse_csv(sample_csv)
        
        # Clean up first
        from audiblimey.db import get_cursor
        with get_cursor() as cur:
            cur.execute("DELETE FROM goodreads_books WHERE import_batch_id = 999")
        
        stats = import_to_db(books, batch_id=999)
        
        assert stats["total"] == 4
        assert stats["inserted"] == 4
        assert stats["with_rating"] == 3  # book 4 has rating 0
        assert stats["with_isbn"] == 3    # book 3 has no ISBN
        assert stats["negative_shelf_count"] == 1  # book 3
        assert stats["positive_shelf_count"] == 2  # books 1 and 2

        # Verify in DB
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM goodreads_books WHERE import_batch_id = 999")
            assert cur.fetchone()[0] == 4
        
        # Cleanup
        with get_cursor() as cur:
            cur.execute("DELETE FROM goodreads_books WHERE import_batch_id = 999")
