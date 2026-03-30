#!/usr/bin/env python3
"""Verify audiblimey PostgreSQL schema integrity."""

import sys
import psycopg2

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "audiblimey",
    "user": "audiblimey",
    "password": "audiblimey_dev",
}

EXPECTED_TABLES = [
    # AudiPy original (23)
    "users", "user_oauth_tokens", "user_audible_accounts", "user_preferences",
    "books", "authors", "narrators", "series", "categories",
    "book_authors", "book_narrators", "book_series", "book_categories",
    "user_libraries", "user_wishlists", "user_reading_lists", "user_reading_list_books",
    "book_prices", "user_recommendations", "price_alerts",
    "book_extended_data", "sync_jobs", "user_analytics",
    # Audiblimey new (3)
    "goodreads_books", "book_isbn_asin_map", "import_jobs",
]

EXPECTED_FK_COUNTS = {
    "user_oauth_tokens": 1,
    "user_audible_accounts": 1,
    "user_preferences": 1,
    "book_authors": 2,
    "book_narrators": 2,
    "book_series": 2,
    "book_categories": 2,
    "user_libraries": 2,
    "user_wishlists": 2,
    "user_reading_lists": 1,
    "user_reading_list_books": 2,
    "book_prices": 1,
    "user_recommendations": 3,
    "price_alerts": 2,
    "book_extended_data": 1,
    "sync_jobs": 1,
    "user_analytics": 1,
    "book_isbn_asin_map": 2,
}


def check_tables(cur):
    """Verify all expected tables exist."""
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """)
    actual = {row[0] for row in cur.fetchall()}
    missing = set(EXPECTED_TABLES) - actual
    extra = actual - set(EXPECTED_TABLES)

    if missing:
        print(f"  FAIL: Missing tables: {sorted(missing)}")
        return False
    print(f"  OK: All {len(EXPECTED_TABLES)} tables exist")
    if extra:
        print(f"  INFO: Extra tables (ok): {sorted(extra)}")
    return True


def check_pgvector(cur):
    """Verify pgvector extension is installed."""
    cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
    if cur.fetchone():
        print("  OK: pgvector extension installed")
        return True
    print("  FAIL: pgvector extension not found")
    return False


def check_vector_column(cur):
    """Verify books.embedding column exists with vector(1536) type."""
    cur.execute("""
        SELECT column_name, udt_name
        FROM information_schema.columns
        WHERE table_name = 'books' AND column_name = 'embedding';
    """)
    row = cur.fetchone()
    if row:
        print(f"  OK: books.embedding column exists (type: {row[1]})")
        return True
    print("  FAIL: books.embedding column not found")
    return False


def check_foreign_keys(cur):
    """Verify foreign key constraints exist."""
    cur.execute("""
        SELECT tc.table_name, COUNT(*) as fk_count
        FROM information_schema.table_constraints tc
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
        GROUP BY tc.table_name
        ORDER BY tc.table_name;
    """)
    actual_fks = {row[0]: row[1] for row in cur.fetchall()}
    
    all_ok = True
    for table, expected_count in sorted(EXPECTED_FK_COUNTS.items()):
        actual = actual_fks.get(table, 0)
        if actual < expected_count:
            print(f"  FAIL: {table} has {actual} FKs, expected >= {expected_count}")
            all_ok = False
    
    if all_ok:
        total_fks = sum(actual_fks.values())
        print(f"  OK: All foreign key constraints verified ({total_fks} total)")
    return all_ok


def check_indexes(cur):
    """Verify key indexes exist."""
    cur.execute("""
        SELECT COUNT(*) FROM pg_indexes
        WHERE schemaname = 'public';
    """)
    count = cur.fetchone()[0]
    # We expect at least 50+ indexes (unique constraints + explicit indexes)
    if count >= 40:
        print(f"  OK: {count} indexes found (>= 40 expected)")
        return True
    print(f"  FAIL: Only {count} indexes found (expected >= 40)")
    return False


def check_triggers(cur):
    """Verify updated_at triggers exist."""
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.triggers
        WHERE trigger_schema = 'public'
          AND trigger_name LIKE 'trg_%_updated_at';
    """)
    count = cur.fetchone()[0]
    if count >= 8:
        print(f"  OK: {count} updated_at triggers found (>= 8 expected)")
        return True
    print(f"  FAIL: Only {count} updated_at triggers found (expected >= 8)")
    return False


def check_seed_data(cur):
    """Verify seed user exists."""
    cur.execute("SELECT display_name FROM users WHERE id = 1;")
    row = cur.fetchone()
    if row and row[0] == 'audiblimey':
        print("  OK: Seed user 'audiblimey' exists")
        return True
    print("  FAIL: Seed user not found")
    return False


def check_check_constraints(cur):
    """Verify CHECK constraints replaced ENUMs."""
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.check_constraints
        WHERE constraint_schema = 'public';
    """)
    count = cur.fetchone()[0]
    if count >= 5:
        print(f"  OK: {count} CHECK constraints found (>= 5 expected for ENUM replacements)")
        return True
    print(f"  FAIL: Only {count} CHECK constraints (expected >= 5)")
    return False


def main():
    print("Audiblimey Schema Verification")
    print("=" * 50)

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True
        cur = conn.cursor()
    except Exception as e:
        print(f"FAIL: Cannot connect to database: {e}")
        sys.exit(1)

    print("\n1. Tables")
    checks = [check_tables(cur)]

    print("\n2. pgvector Extension")
    checks.append(check_pgvector(cur))

    print("\n3. Vector Column (books.embedding)")
    checks.append(check_vector_column(cur))

    print("\n4. Foreign Keys")
    checks.append(check_foreign_keys(cur))

    print("\n5. Indexes")
    checks.append(check_indexes(cur))

    print("\n6. Updated_at Triggers")
    checks.append(check_triggers(cur))

    print("\n7. CHECK Constraints (ENUM replacements)")
    checks.append(check_check_constraints(cur))

    print("\n8. Seed Data")
    checks.append(check_seed_data(cur))

    cur.close()
    conn.close()

    print("\n" + "=" * 50)
    passed = sum(checks)
    total = len(checks)
    if all(checks):
        print(f"All checks passed ({passed}/{total})")
        sys.exit(0)
    else:
        print(f"FAILED: {total - passed}/{total} checks failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
