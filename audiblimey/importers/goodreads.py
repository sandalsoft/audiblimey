"""Goodreads CSV export parser for audiblimey.

Parses the standard Goodreads library export CSV format and imports
book data into the goodreads_books table. Classifies shelves into
signal types (positive, negative, neutral, genre) for recommendation scoring.
"""

import csv
import hashlib
import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from audiblimey.db import get_cursor

logger = logging.getLogger(__name__)

# Shelf classification for recommendation signals
NEGATIVE_SHELVES = frozenset({
    "abandoned", "dnf", "did-not-finish", "didnt-finish",
    "gave-up", "couldn-t-finish", "couldnt-finish", "not-for-me",
    "dropped", "quit", "unfinished",
})

POSITIVE_SHELVES = frozenset({
    "favorites", "favourites", "loved", "all-time-favorites",
    "best-books", "top-picks", "5-stars", "five-stars",
    "masterpiece", "reread", "re-read",
})

NEUTRAL_SHELVES = frozenset({
    "to-read", "currently-reading", "read", "owned",
    "want-to-read", "tbr", "on-hold",
})


@dataclass
class GoodreadsBook:
    """Parsed Goodreads book entry."""
    goodreads_book_id: str = ""
    title: str = ""
    author: str = ""
    additional_authors: str = ""
    isbn: str = ""
    isbn13: str = ""
    my_rating: int = 0
    average_rating: float = 0.0
    num_pages: Optional[int] = None
    original_publication_year: Optional[int] = None
    date_read: Optional[date] = None
    date_added: Optional[date] = None
    bookshelves: str = ""
    exclusive_shelf: str = ""
    my_review: str = ""

    # Derived fields
    shelf_list: list = field(default_factory=list)
    positive_shelves: list = field(default_factory=list)
    negative_shelves: list = field(default_factory=list)
    genre_shelves: list = field(default_factory=list)


def classify_shelves(shelf_string: str) -> tuple[list, list, list, list]:
    """Classify shelf names into signal types.
    
    Returns: (all_shelves, positive, negative, genre)
    """
    if not shelf_string:
        return [], [], [], []
    
    shelves = [s.strip().lower() for s in shelf_string.split(",") if s.strip()]
    positive = [s for s in shelves if s in POSITIVE_SHELVES]
    negative = [s for s in shelves if s in NEGATIVE_SHELVES]
    genre = [s for s in shelves if s not in POSITIVE_SHELVES 
             and s not in NEGATIVE_SHELVES and s not in NEUTRAL_SHELVES]
    
    return shelves, positive, negative, genre


def _clean_isbn(raw: str) -> str:
    """Clean ISBN field from Goodreads export (strips = and quotes)."""
    if not raw:
        return ""
    return raw.strip().strip('="').strip('"').strip("'").strip()


def _parse_date(date_str: str) -> Optional[date]:
    """Parse a date string from Goodreads CSV."""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def _parse_int(val: str) -> Optional[int]:
    """Safely parse an integer."""
    if not val or not val.strip():
        return None
    try:
        return int(float(val.strip()))
    except (ValueError, TypeError):
        return None


def _parse_float(val: str) -> float:
    """Safely parse a float, defaulting to 0.0."""
    if not val or not val.strip():
        return 0.0
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return 0.0


def parse_csv(csv_path: str | Path) -> list[GoodreadsBook]:
    """Parse a Goodreads CSV export file.
    
    Args:
        csv_path: Path to the Goodreads export CSV file
        
    Returns:
        List of parsed GoodreadsBook objects
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Goodreads CSV not found: {csv_path}")
    
    books = []
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        
        for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
            try:
                shelves_str = row.get("Bookshelves", "")
                all_shelves, positive, negative, genre = classify_shelves(shelves_str)
                
                book = GoodreadsBook(
                    goodreads_book_id=row.get("Book Id", "").strip(),
                    title=row.get("Title", "").strip(),
                    author=row.get("Author", "").strip(),
                    additional_authors=row.get("Additional Authors", "").strip(),
                    isbn=_clean_isbn(row.get("ISBN", "")),
                    isbn13=_clean_isbn(row.get("ISBN13", "")),
                    my_rating=_parse_int(row.get("My Rating", "0")) or 0,
                    average_rating=_parse_float(row.get("Average Rating", "0")),
                    num_pages=_parse_int(row.get("Number of Pages", "")),
                    original_publication_year=_parse_int(row.get("Original Publication Year", "")),
                    date_read=_parse_date(row.get("Date Read", "")),
                    date_added=_parse_date(row.get("Date Added", "")),
                    bookshelves=shelves_str,
                    exclusive_shelf=row.get("Exclusive Shelf", "").strip(),
                    my_review=row.get("My Review", "").strip(),
                    shelf_list=all_shelves,
                    positive_shelves=positive,
                    negative_shelves=negative,
                    genre_shelves=genre,
                )
                books.append(book)
                
            except Exception as e:
                logger.warning(f"Row {row_num}: Failed to parse: {e}")
                continue
    
    return books


def import_to_db(books: list[GoodreadsBook], batch_id: int) -> dict:
    """Import parsed Goodreads books into the database.
    
    Args:
        books: List of parsed GoodreadsBook objects
        batch_id: Import job ID for tracking
        
    Returns:
        Import statistics dict
    """
    stats = {
        "total": len(books),
        "inserted": 0,
        "skipped": 0,
        "with_isbn": 0,
        "with_rating": 0,
        "with_review": 0,
        "negative_shelf_count": 0,
        "positive_shelf_count": 0,
        "shelf_distribution": {},
    }
    
    with get_cursor() as cur:
        for book in books:
            try:
                cur.execute("""
                    INSERT INTO goodreads_books 
                    (goodreads_book_id, title, author, additional_authors, isbn, isbn13,
                     my_rating, average_rating, num_pages, original_publication_year,
                     date_read, date_added, bookshelves, exclusive_shelf, my_review,
                     import_batch_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (
                    book.goodreads_book_id, book.title, book.author,
                    book.additional_authors, book.isbn, book.isbn13,
                    book.my_rating, book.average_rating, book.num_pages,
                    book.original_publication_year, book.date_read, book.date_added,
                    book.bookshelves, book.exclusive_shelf, book.my_review,
                    batch_id,
                ))
                stats["inserted"] += 1
                
                # Track stats
                if book.isbn13:
                    stats["with_isbn"] += 1
                if book.my_rating > 0:
                    stats["with_rating"] += 1
                if book.my_review:
                    stats["with_review"] += 1
                if book.negative_shelves:
                    stats["negative_shelf_count"] += 1
                if book.positive_shelves:
                    stats["positive_shelf_count"] += 1
                
                for shelf in book.shelf_list:
                    stats["shelf_distribution"][shelf] = stats["shelf_distribution"].get(shelf, 0) + 1
                    
            except Exception as e:
                logger.warning(f"Failed to insert '{book.title}': {e}")
                stats["skipped"] += 1
    
    return stats


def file_hash(csv_path: str | Path) -> str:
    """Compute SHA256 hash of a file for deduplication."""
    h = hashlib.sha256()
    with open(csv_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
