"""Import routes for audiblimey API."""

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from audiblimey.cli.import_goodreads import run_import
from audiblimey.db import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["imports"])


@router.post("/import/goodreads")
async def import_goodreads(
    file: UploadFile = File(...),
    skip_matching: bool = False,
    use_openlibrary: bool = True,
):
    """Import a Goodreads CSV export file.
    
    Upload a CSV file exported from Goodreads (My Books > Import/Export).
    The file will be parsed, imported, and books will be matched to Audible ASINs.
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV file")
    
    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        import_stats, match_stats = run_import(
            tmp_path,
            skip_matching=skip_matching,
            use_openlibrary=use_openlibrary,
        )
        
        return {
            "status": "success",
            "import": {
                "total_books": import_stats["total"],
                "inserted": import_stats["inserted"],
                "with_isbn": import_stats["with_isbn"],
                "with_rating": import_stats["with_rating"],
                "negative_shelves": import_stats["negative_shelf_count"],
                "positive_shelves": import_stats["positive_shelf_count"],
            },
            "matching": {
                "total_attempted": match_stats.get("total", 0),
                "matched_isbn_direct": match_stats.get("matched_isbn_direct", 0),
                "matched_openlibrary": match_stats.get("matched_openlibrary", 0),
                "matched_fuzzy": match_stats.get("matched_fuzzy", 0),
                "unmatched": match_stats.get("unmatched", 0),
                "match_rate": match_stats.get("match_rate", 0.0),
            },
        }
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise HTTPException(500, f"Import failed: {str(e)}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/import/history")
async def import_history():
    """Get history of all import jobs."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT id, import_type, total_rows, matched_count, unmatched_count,
                   match_rate, status, started_at, completed_at
            FROM import_jobs
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
    
    return {
        "imports": [
            {
                "id": r[0],
                "type": r[1],
                "total_rows": r[2],
                "matched": r[3],
                "unmatched": r[4],
                "match_rate": float(r[5]) if r[5] else 0.0,
                "status": r[6],
                "started_at": r[7].isoformat() if r[7] else None,
                "completed_at": r[8].isoformat() if r[8] else None,
            }
            for r in rows
        ]
    }


@router.get("/import/stats")
async def import_stats():
    """Get current import statistics."""
    with get_cursor() as cur:
        # Total Goodreads books
        cur.execute("SELECT COUNT(*) FROM goodreads_books")
        total_goodreads = cur.fetchone()[0]
        
        # Rating distribution
        cur.execute("""
            SELECT my_rating, COUNT(*) 
            FROM goodreads_books 
            WHERE my_rating > 0
            GROUP BY my_rating 
            ORDER BY my_rating
        """)
        rating_dist = {str(r[0]): r[1] for r in cur.fetchall()}
        
        # Matched vs unmatched
        cur.execute("SELECT COUNT(*) FROM book_isbn_asin_map")
        total_matched = cur.fetchone()[0]
        
        # Match source distribution
        cur.execute("""
            SELECT match_source, COUNT(*)
            FROM book_isbn_asin_map
            GROUP BY match_source
        """)
        match_sources = {r[0]: r[1] for r in cur.fetchall()}
        
        # Shelf distribution (top 20)
        cur.execute("""
            SELECT unnest(string_to_array(bookshelves, ', ')), COUNT(*)
            FROM goodreads_books
            WHERE bookshelves != ''
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT 20
        """)
        shelves = {r[0]: r[1] for r in cur.fetchall()}
    
    return {
        "total_goodreads_books": total_goodreads,
        "total_matched": total_matched,
        "total_unmatched": total_goodreads - total_matched,
        "match_rate": round(total_matched / max(total_goodreads, 1) * 100, 1),
        "rating_distribution": rating_dist,
        "match_sources": match_sources,
        "top_shelves": shelves,
    }
