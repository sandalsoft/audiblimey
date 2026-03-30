"""CLI tool for importing Goodreads CSV exports into audiblimey."""

import argparse
import logging
import sys
from pathlib import Path

from audiblimey.db import get_cursor
from audiblimey.importers.goodreads import parse_csv, import_to_db, file_hash
from audiblimey.matching.isbn_asin import match_all_goodreads_books

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def create_import_job(csv_path: Path) -> int:
    """Create an import job record and return its ID."""
    fhash = file_hash(csv_path)
    
    with get_cursor() as cur:
        # Check for duplicate import
        cur.execute(
            "SELECT id FROM import_jobs WHERE file_hash = %s AND status = 'completed'",
            (fhash,)
        )
        existing = cur.fetchone()
        if existing:
            logger.warning(f"This file was already imported (job #{existing[0]}). Re-importing.")
        
        cur.execute("""
            INSERT INTO import_jobs (import_type, file_hash, status, started_at)
            VALUES ('goodreads', %s, 'running', NOW())
            RETURNING id
        """, (fhash,))
        return cur.fetchone()[0]


def update_import_job(job_id: int, stats: dict, match_stats: dict):
    """Update import job with final statistics."""
    total_matched = (
        match_stats.get("matched_isbn_direct", 0) +
        match_stats.get("matched_openlibrary", 0) +
        match_stats.get("matched_fuzzy", 0) +
        match_stats.get("matched_fuzzy_title", 0)
    )
    
    with get_cursor() as cur:
        cur.execute("""
            UPDATE import_jobs SET
                status = 'completed',
                completed_at = NOW(),
                total_rows = %s,
                matched_count = %s,
                unmatched_count = %s,
                match_rate = %s
            WHERE id = %s
        """, (
            stats["total"],
            total_matched,
            match_stats.get("unmatched", 0),
            match_stats.get("match_rate", 0.0),
            job_id,
        ))


def run_import(csv_path: str, skip_matching: bool = False, use_openlibrary: bool = True):
    """Run the full Goodreads import pipeline.
    
    Steps:
    1. Parse CSV file
    2. Import to goodreads_books table
    3. Run ISBN-to-ASIN matching
    4. Generate report
    """
    csv_path = Path(csv_path)
    logger.info(f"Starting Goodreads import from {csv_path}")
    
    # Step 1: Create import job
    job_id = create_import_job(csv_path)
    logger.info(f"Import job #{job_id} created")
    
    try:
        # Step 2: Parse CSV
        logger.info("Parsing CSV...")
        books = parse_csv(csv_path)
        logger.info(f"Parsed {len(books)} books from CSV")
        
        # Step 3: Import to DB
        logger.info("Importing to database...")
        import_stats = import_to_db(books, batch_id=job_id)
        logger.info(f"Imported: {import_stats['inserted']} books")
        logger.info(f"  With ISBN: {import_stats['with_isbn']}")
        logger.info(f"  With rating: {import_stats['with_rating']}")
        logger.info(f"  With review: {import_stats['with_review']}")
        logger.info(f"  Negative shelves: {import_stats['negative_shelf_count']}")
        logger.info(f"  Positive shelves: {import_stats['positive_shelf_count']}")
        
        # Step 4: Run matching
        match_stats = {"total": 0, "match_rate": 0.0, "unmatched": 0}
        if not skip_matching:
            logger.info("Running ISBN-to-ASIN matching...")
            match_stats = match_all_goodreads_books(
                use_openlibrary=use_openlibrary,
                batch_id=job_id,
            )
            logger.info(f"Match results:")
            logger.info(f"  Total: {match_stats['total']}")
            logger.info(f"  ISBN direct: {match_stats.get('matched_isbn_direct', 0)}")
            logger.info(f"  Open Library: {match_stats.get('matched_openlibrary', 0)}")
            logger.info(f"  Fuzzy title: {match_stats.get('matched_fuzzy', 0)}")
            logger.info(f"  Unmatched: {match_stats['unmatched']}")
            logger.info(f"  Match rate: {match_stats['match_rate']}%")
        
        # Step 5: Update job
        update_import_job(job_id, import_stats, match_stats)
        
        # Step 6: Print shelf distribution
        if import_stats.get("shelf_distribution"):
            logger.info("\nShelf distribution:")
            for shelf, count in sorted(
                import_stats["shelf_distribution"].items(),
                key=lambda x: -x[1]
            )[:20]:
                logger.info(f"  {shelf}: {count}")
        
        logger.info(f"\nImport complete! Job #{job_id}")
        return import_stats, match_stats
        
    except Exception as e:
        with get_cursor() as cur:
            cur.execute(
                "UPDATE import_jobs SET status = 'failed', error_message = %s WHERE id = %s",
                (str(e), job_id)
            )
        logger.error(f"Import failed: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Import Goodreads CSV export into audiblimey")
    parser.add_argument("csv_file", help="Path to Goodreads CSV export file")
    parser.add_argument("--skip-matching", action="store_true",
                       help="Skip ISBN-to-ASIN matching (import CSV only)")
    parser.add_argument("--no-openlibrary", action="store_true",
                       help="Skip Open Library API lookups (use local matching only)")
    
    args = parser.parse_args()
    
    try:
        run_import(
            args.csv_file,
            skip_matching=args.skip_matching,
            use_openlibrary=not args.no_openlibrary,
        )
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
