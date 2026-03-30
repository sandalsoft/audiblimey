# Audiblimey Database

## Overview

PostgreSQL 16 + pgvector, migrated from AudiPy's MySQL schema.

## Quick Start

```bash
# Start PostgreSQL
docker compose up -d

# Verify schema
pip install psycopg2-binary
python scripts/verify_schema.py

# Seed test data
python scripts/seed_test_data.py
```

## Connection

| Parameter | Value |
|---|---|
| Host | localhost |
| Port | 5432 |
| Database | audiblimey |
| User | audiblimey |
| Password | audiblimey_dev |

```
psql postgresql://audiblimey:audiblimey_dev@localhost:5432/audiblimey
```

## Schema

26 tables across 8 sections:

1. **Users & Auth** (4): users, user_oauth_tokens, user_audible_accounts, user_preferences
2. **Core Entities** (5): books, authors, narrators, series, categories
3. **Relationships** (4): book_authors, book_narrators, book_series, book_categories
4. **User Library** (4): user_libraries, user_wishlists, user_reading_lists, user_reading_list_books
5. **Pricing & Recs** (3): book_prices, user_recommendations, price_alerts
6. **Extended Data** (1): book_extended_data
7. **System** (2): sync_jobs, user_analytics
8. **Goodreads** (3): goodreads_books, book_isbn_asin_map, import_jobs

## Audiblimey Additions

- `books.embedding` — `vector(1536)` column for pgvector similarity search
- `books.search_vector` — tsvector column with GIN index for full-text search
- `user_recommendations` — extended with rating_weight, recency_factor, negative_adjustment, series_urgency, score_breakdown (JSONB), explanation_text
- `goodreads_books` — raw Goodreads CSV import data
- `book_isbn_asin_map` — ISBN↔ASIN bridge for Goodreads-Audible matching
- `import_jobs` — import tracking for idempotency

## Migrations

Migrations are in `db/migrations/` and auto-run on first `docker compose up`:

- `001_initial_schema.sql` — Full schema creation + pgvector + seed user
