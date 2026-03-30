"""ISBN-to-ASIN matching service for audiblimey.

Matches Goodreads books (identified by ISBN13/ISBN) to Audible books (identified by ASIN)
using multiple strategies:
1. Direct ISBN match against books.isbn in the local database
2. Open Library API lookup for ISBN → identifiers → Amazon ASIN
3. Fuzzy title+author matching against local Audible library
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import psycopg2

from audiblimey.db import get_cursor

logger = logging.getLogger(__name__)

# Open Library rate limit: be conservative
OPENLIBRARY_DELAY_SECONDS = 0.5
FUZZY_TITLE_THRESHOLD = 0.6  # pg_trgm similarity threshold


@dataclass
class MatchResult:
    """Result of an ISBN-to-ASIN match attempt."""
    isbn13: str
    isbn: str
    asin: Optional[str] = None
    match_source: Optional[str] = None  # 'isbn_direct', 'openlibrary', 'fuzzy_title'
    confidence: float = 0.0
    goodreads_book_id: Optional[int] = None
    title: str = ""
    author: str = ""


def match_isbn_direct(isbn13: str, isbn: str) -> Optional[MatchResult]:
    """Try to match ISBN directly against books.isbn in local DB.
    
    This catches cases where Audible books have ISBN metadata stored.
    """
    with get_cursor() as cur:
        # Try ISBN13 first, then ISBN10
        for isbn_val in [isbn13, isbn]:
            if not isbn_val:
                continue
            cur.execute(
                "SELECT asin FROM books WHERE isbn = %s LIMIT 1",
                (isbn_val,)
            )
            row = cur.fetchone()
            if row:
                return MatchResult(
                    isbn13=isbn13,
                    isbn=isbn,
                    asin=row[0],
                    match_source="isbn_direct",
                    confidence=0.95,
                )
    return None


def match_via_openlibrary(isbn13: str, isbn: str) -> Optional[MatchResult]:
    """Look up ISBN on Open Library API and extract Amazon ASIN from identifiers.
    
    Open Library stores Amazon ASINs in its identifiers field for some books.
    API: https://openlibrary.org/isbn/{isbn}.json
    """
    import urllib.request
    import json
    
    isbn_to_try = isbn13 or isbn
    if not isbn_to_try:
        return None
    
    url = f"https://openlibrary.org/isbn/{isbn_to_try}.json"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "audiblimey/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read().decode())
        
        # Check identifiers for Amazon ASIN
        identifiers = data.get("identifiers", {})
        amazon_ids = identifiers.get("amazon", [])
        
        if amazon_ids:
            return MatchResult(
                isbn13=isbn13,
                isbn=isbn,
                asin=amazon_ids[0],
                match_source="openlibrary",
                confidence=0.85,
            )
        
        # Also check if there's a direct ASIN in other fields
        # Open Library sometimes stores it differently
        for key in ["asin", "amazon_id"]:
            val = identifiers.get(key, [])
            if val:
                return MatchResult(
                    isbn13=isbn13,
                    isbn=isbn,
                    asin=val[0] if isinstance(val, list) else val,
                    match_source="openlibrary",
                    confidence=0.80,
                )
                
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.debug(f"ISBN {isbn_to_try} not found on Open Library")
        else:
            logger.warning(f"Open Library API error for {isbn_to_try}: {e}")
    except Exception as e:
        logger.warning(f"Open Library lookup failed for {isbn_to_try}: {e}")
    
    return None


def match_fuzzy_title(title: str, author: str) -> Optional[MatchResult]:
    """Fuzzy match by title + author against local Audible library using pg_trgm.
    
    Falls back to this when ISBN-based matching fails.
    """
    if not title:
        return None
    
    with get_cursor() as cur:
        # Use pg_trgm similarity for fuzzy matching
        # Join with authors to also match author name
        cur.execute("""
            SELECT b.asin, b.title,
                   similarity(lower(b.title), lower(%s)) as title_sim,
                   a.name as author_name
            FROM books b
            LEFT JOIN book_authors ba ON b.id = ba.book_id
            LEFT JOIN authors a ON ba.author_id = a.id
            WHERE similarity(lower(b.title), lower(%s)) > %s
            ORDER BY similarity(lower(b.title), lower(%s)) DESC
            LIMIT 5
        """, (title, title, FUZZY_TITLE_THRESHOLD, title))
        
        rows = cur.fetchall()
        
        if not rows:
            return None
        
        # If we have an author, prefer matches where author also matches
        if author:
            for row in rows:
                asin, book_title, title_sim, author_name = row
                if author_name and _author_matches(author, author_name):
                    return MatchResult(
                        isbn13="",
                        isbn="",
                        asin=asin,
                        match_source="fuzzy_title",
                        confidence=round(min(title_sim * 0.8, 0.75), 2),
                        title=book_title,
                        author=author_name or "",
                    )
        
        # Fall back to best title match
        asin, book_title, title_sim, author_name = rows[0]
        return MatchResult(
            isbn13="",
            isbn="",
            asin=asin,
            match_source="fuzzy_title",
            confidence=round(min(title_sim * 0.7, 0.65), 2),
            title=book_title,
            author=author_name or "",
        )


def _author_matches(goodreads_author: str, audible_author: str) -> bool:
    """Check if two author names likely refer to the same person."""
    a = goodreads_author.lower().strip()
    b = audible_author.lower().strip()
    
    if a == b:
        return True
    
    # Check if one contains the other (handles "Brandon Sanderson" vs "Sanderson, Brandon")
    a_parts = set(a.replace(",", "").split())
    b_parts = set(b.replace(",", "").split())
    
    # If all significant parts of one name appear in the other
    return len(a_parts & b_parts) >= min(len(a_parts), len(b_parts))


def match_all_goodreads_books(
    use_openlibrary: bool = True,
    batch_id: Optional[int] = None,
    limit: Optional[int] = None,
) -> dict:
    """Run matching for all unmatched Goodreads books.
    
    Strategy order:
    1. Direct ISBN match against local DB
    2. Open Library API (if enabled)
    3. Fuzzy title+author match
    
    Args:
        use_openlibrary: Whether to use Open Library API (slower, rate-limited)
        batch_id: Optional import batch to restrict matching to
        limit: Optional limit on number of books to process
        
    Returns:
        Match statistics dict
    """
    stats = {
        "total": 0,
        "matched_isbn_direct": 0,
        "matched_openlibrary": 0,
        "matched_fuzzy": 0,
        "unmatched": 0,
        "errors": 0,
        "match_rate": 0.0,
    }
    
    # Get unmatched Goodreads books
    with get_cursor() as cur:
        query = """
            SELECT gb.id, gb.isbn13, gb.isbn, gb.title, gb.author
            FROM goodreads_books gb
            LEFT JOIN book_isbn_asin_map m ON gb.id = m.goodreads_book_id
            WHERE m.id IS NULL
        """
        params = []
        if batch_id:
            query += " AND gb.import_batch_id = %s"
            params.append(batch_id)
        if limit:
            query += f" LIMIT {int(limit)}"
        
        cur.execute(query, params)
        books = cur.fetchall()
    
    stats["total"] = len(books)
    logger.info(f"Matching {len(books)} Goodreads books...")
    
    for gb_id, isbn13, isbn, title, author in books:
        result = None
        
        try:
            # Strategy 1: Direct ISBN match
            if isbn13 or isbn:
                result = match_isbn_direct(isbn13 or "", isbn or "")
            
            # Strategy 2: Open Library
            if not result and use_openlibrary and (isbn13 or isbn):
                result = match_via_openlibrary(isbn13 or "", isbn or "")
                time.sleep(OPENLIBRARY_DELAY_SECONDS)
            
            # Strategy 3: Fuzzy title+author
            if not result:
                result = match_fuzzy_title(title, author or "")
            
            if result and result.asin:
                # Verify ASIN exists in our books table
                with get_cursor() as cur:
                    cur.execute("SELECT 1 FROM books WHERE asin = %s", (result.asin,))
                    if cur.fetchone():
                        # Store the match
                        cur.execute("""
                            INSERT INTO book_isbn_asin_map 
                            (isbn13, isbn, asin, goodreads_book_id, match_source, confidence)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                        """, (
                            isbn13 or "", isbn or "", result.asin,
                            gb_id, result.match_source, result.confidence,
                        ))
                        
                        stats[f"matched_{result.match_source}"] = \
                            stats.get(f"matched_{result.match_source}", 0) + 1
                    else:
                        # ASIN not in our library — still store for reference but mark differently
                        stats["unmatched"] += 1
                        logger.debug(f"ASIN {result.asin} for '{title}' not in local library")
            else:
                stats["unmatched"] += 1
                
        except Exception as e:
            logger.warning(f"Error matching '{title}': {e}")
            stats["errors"] += 1
    
    total_matched = (
        stats.get("matched_isbn_direct", 0) +
        stats.get("matched_openlibrary", 0) +
        stats.get("matched_fuzzy", 0) +
        stats.get("matched_fuzzy_title", 0)
    )
    stats["match_rate"] = round(total_matched / max(stats["total"], 1) * 100, 1)
    
    return stats
