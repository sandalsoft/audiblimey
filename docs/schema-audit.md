# AudiPy MySQL Schema Audit

Source: `dbarkman/AudiPy` — `setup_database.sql`
Tables: 23 (original) + 2 (audiblimey additions) = 25 total

## MySQL → PostgreSQL Type Mapping

| MySQL Type | PostgreSQL Type | Notes |
|---|---|---|
| `BIGINT AUTO_INCREMENT` | `BIGSERIAL` | Primary keys |
| `TINYINT(1)` / `BOOLEAN` | `BOOLEAN` | Direct mapping |
| `VARCHAR(N)` | `VARCHAR(N)` | Direct mapping |
| `TEXT` | `TEXT` | Direct mapping |
| `DECIMAL(M,N)` | `DECIMAL(M,N)` | Direct mapping |
| `INT` | `INTEGER` | Direct mapping |
| `DATE` | `DATE` | Direct mapping |
| `TIMESTAMP` | `TIMESTAMPTZ` | Use timezone-aware |
| `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | `TIMESTAMPTZ DEFAULT NOW()` | |
| `ON UPDATE CURRENT_TIMESTAMP` | Trigger or application-level | PostgreSQL has no ON UPDATE CURRENT_TIMESTAMP |
| `ENUM(...)` | `VARCHAR + CHECK` | PostgreSQL has no native ENUM inline; use CHECK constraints |
| `JSON` | `JSONB` | Use JSONB for indexable JSON |
| `FULLTEXT INDEX` | `tsvector + GIN index` | PostgreSQL full-text search |
| `UNIQUE KEY name (cols)` | `UNIQUE (cols)` | Named constraints syntax differs |
| `INDEX idx_name (col)` | `CREATE INDEX idx_name ON table (col)` | Separate CREATE INDEX statements |
| `INDEX idx_name (col(N))` | `CREATE INDEX ... ON table (col)` | No prefix length in PostgreSQL |

## Table: users
- **Section**: Users & Authentication
- **Columns**: id (PK), oauth_provider, oauth_provider_id, display_name, avatar_url, created_at, updated_at, last_login, is_active
- **Indexes**: unique_oauth_user(provider, provider_id), idx_provider, idx_created_at, idx_active, idx_last_login
- **MySQL-specific**: `ON UPDATE CURRENT_TIMESTAMP` on updated_at → needs trigger
- **Audiblimey note**: Single-user, simplify auth. Keep table for schema compatibility but default to single user.

## Table: user_oauth_tokens
- **Section**: Users & Authentication
- **Columns**: id (PK), user_id (FK→users), provider, access_token, refresh_token, token_expires_at, scope, created_at, updated_at
- **Indexes**: unique_user_provider, idx_user_id, idx_expires_at
- **MySQL-specific**: `ON UPDATE CURRENT_TIMESTAMP`

## Table: user_audible_accounts
- **Section**: Users & Authentication
- **Columns**: id (PK), user_id (FK→users), encrypted_auth_data, marketplace, last_sync, sync_status, sync_error, tokens_expires_at, created_at, updated_at
- **MySQL-specific**: `ENUM('pending','syncing','completed','failed')` → `VARCHAR(20) CHECK (sync_status IN (...))`
- **MySQL-specific**: `ON UPDATE CURRENT_TIMESTAMP`

## Table: user_preferences
- **Section**: Users & Authentication
- **Columns**: id (PK), user_id (FK→users), max_price, preferred_language, marketplace, currency, notifications_enabled, price_alert_enabled, new_release_alerts, created_at, updated_at
- **Indexes**: unique_user_prefs
- **MySQL-specific**: `ON UPDATE CURRENT_TIMESTAMP`

## Table: books
- **Section**: Core Book Entities
- **Columns**: id (PK), asin (UNIQUE), amazon_asin, title, subtitle, publisher_name, publication_datetime, publication_name, issue_date, release_date, isbn, language, content_type, content_delivery_type, format_type, runtime_length_min, merchandising_summary, merchandising_description, extended_product_description, audible_editors_summary, publisher_summary, is_adult_product, is_listenable, is_purchasability_suppressed, is_vvab, has_children, sku, sku_lite, created_at, updated_at
- **Indexes**: idx_asin, idx_title(100), idx_language, idx_publisher(100), idx_release_date, idx_runtime, FULLTEXT(title,subtitle), FULLTEXT(descriptions)
- **MySQL-specific**: FULLTEXT → tsvector + GIN; prefix indexes → full column indexes; `ON UPDATE CURRENT_TIMESTAMP`
- **Audiblimey addition**: `embedding vector(1536)` column for pgvector

## Table: authors
- **Section**: Core Book Entities
- **Columns**: id (PK), asin (UNIQUE), name, created_at, updated_at
- **Indexes**: idx_name(100), idx_asin
- **MySQL-specific**: prefix index, `ON UPDATE CURRENT_TIMESTAMP`

## Table: narrators
- **Section**: Core Book Entities
- **Columns**: id (PK), asin (UNIQUE), name, created_at, updated_at
- **Indexes**: idx_name(100), idx_asin
- **MySQL-specific**: prefix index, `ON UPDATE CURRENT_TIMESTAMP`

## Table: series
- **Section**: Core Book Entities
- **Columns**: id (PK), asin (UNIQUE), title, description, created_at, updated_at
- **Indexes**: idx_title(100), idx_asin
- **MySQL-specific**: prefix index, `ON UPDATE CURRENT_TIMESTAMP`

## Table: categories
- **Section**: Core Book Entities
- **Columns**: id (PK), audible_category_id, name, parent_id (FK→categories), level, full_path, created_at
- **Indexes**: idx_name(100), idx_parent, idx_level
- **MySQL-specific**: prefix index

## Table: book_authors
- **Section**: Relationships
- **Columns**: id (PK), book_id (FK→books), author_id (FK→authors), role, display_order
- **Indexes**: unique_book_author, idx_book_id, idx_author_id
- **Cascades**: ON DELETE CASCADE from both FKs

## Table: book_narrators
- **Section**: Relationships
- **Columns**: id (PK), book_id (FK→books), narrator_id (FK→narrators), display_order
- **Indexes**: unique_book_narrator, idx_book_id, idx_narrator_id
- **Cascades**: ON DELETE CASCADE from both FKs

## Table: book_series
- **Section**: Relationships
- **Columns**: id (PK), book_id (FK→books), series_id (FK→series), sequence, sequence_display
- **Indexes**: unique_book_series, idx_book_id, idx_series_id, idx_sequence
- **Cascades**: ON DELETE CASCADE from both FKs
- **Note**: sequence is DECIMAL(10,2) for fractional entries like "1.5"

## Table: book_categories
- **Section**: Relationships
- **Columns**: id (PK), book_id (FK→books), category_id (FK→categories)
- **Indexes**: unique_book_category, idx_book_id, idx_category_id
- **Cascades**: ON DELETE CASCADE from both FKs

## Table: user_libraries
- **Section**: User Library & Progress
- **Columns**: id (PK), user_id (FK→users), book_id (FK→books), purchase_date, order_id, order_item_id, date_added, is_pending, is_preordered, is_removable, is_visible, is_archived, percent_complete, is_finished, is_downloaded, is_playable, is_in_wishlist, user_rating, created_at, updated_at
- **Indexes**: unique_user_book, idx_user_id, idx_book_id, idx_purchase_date, idx_is_finished, idx_percent_complete
- **MySQL-specific**: `ON UPDATE CURRENT_TIMESTAMP`
- **Key for audiblimey**: user_rating and percent_complete are core taste signals

## Table: user_wishlists
- **Section**: User Library & Progress
- **Columns**: id (PK), user_id (FK→users), book_id (FK→books), priority, notes, added_date
- **Indexes**: unique_user_wishlist, idx_user_id, idx_priority, idx_added_date

## Table: user_reading_lists
- **Section**: User Library & Progress
- **Columns**: id (PK), user_id (FK→users), name, description, is_public, created_at, updated_at
- **Indexes**: idx_user_id, idx_name

## Table: user_reading_list_books
- **Section**: User Library & Progress
- **Columns**: id (PK), reading_list_id (FK→user_reading_lists), book_id (FK→books), position, added_date
- **Indexes**: unique_list_book, idx_reading_list_id, idx_position

## Table: book_prices
- **Section**: Pricing & Suggestions
- **Columns**: id (PK), book_id (FK→books), marketplace, credit_price, list_price, member_price, currency_code, price_date, created_at
- **Indexes**: unique_book_price_date, idx_book_id, idx_price_date, idx_member_price

## Table: user_recommendations
- **Section**: Pricing & Suggestions
- **Columns**: id (PK), user_id (FK→users), book_id (FK→books), suggestion_type, source_book_id (FK→books), source_name, confidence_score, purchase_method, generated_at, is_dismissed
- **MySQL-specific**: `ENUM('series','author','narrator','similar')` → CHECK constraint; `ENUM('cash','credits')` → CHECK constraint
- **Key for audiblimey**: Will be extended with rating-weighted scoring fields and explainability JSON

## Table: price_alerts
- **Section**: Pricing & Suggestions
- **Columns**: id (PK), user_id (FK→users), book_id (FK→books), target_price, alert_type, percentage_threshold, is_active, last_notified, created_at
- **MySQL-specific**: `ENUM('below','percentage_off')` → CHECK constraint

## Table: book_extended_data
- **Section**: Extended Book Data
- **Columns**: id (PK), book_id (FK→books), product_images, social_media_images, rich_images, customer_reviews, goodreads_ratings, rating, 20+ boolean flags, 10+ date fields, 10+ ID/reference fields, content details, series/episode data, technical data, URLs, tags/keywords, other
- **MySQL-specific**: All `JSON` columns → `JSONB`
- **Note**: 142+ fields stored across books + book_extended_data tables

## Table: sync_jobs
- **Section**: System & Analytics
- **Columns**: id (PK), user_id (FK→users), job_type, status, started_at, completed_at, books_processed, books_added, books_updated, error_message, created_at
- **MySQL-specific**: Two ENUM fields → CHECK constraints

## Table: user_analytics
- **Section**: System & Analytics
- **Columns**: id (PK), user_id (FK→users), action_type, entity_type, entity_id, metadata, created_at
- **MySQL-specific**: `JSON` → `JSONB`

---

## Audiblimey Additional Tables

## Table: goodreads_books (NEW)
- **Section**: Goodreads Integration
- **Columns**: id (PK), goodreads_book_id, title, author, additional_authors, isbn, isbn13, my_rating, average_rating, num_pages, original_publication_year, date_read, date_added, bookshelves, exclusive_shelf, my_review, import_batch_id, created_at
- **Purpose**: Raw Goodreads CSV import storage

## Table: book_isbn_asin_map (NEW)
- **Section**: Goodreads Integration
- **Columns**: id (PK), isbn13 (indexed), asin (indexed, FK→books.asin), match_source, confidence, matched_at, created_at
- **Purpose**: Bridge table connecting Goodreads ISBN13 to Audible ASIN
- **match_source values**: 'openlibrary', 'fuzzy_title', 'manual'

## Table: import_jobs (NEW)
- **Section**: System
- **Columns**: id (PK), import_type, file_hash, total_rows, matched_count, unmatched_count, match_rate, started_at, completed_at, status, created_at
- **Purpose**: Track Goodreads import runs for idempotency and reporting

---

## Summary

| Category | Tables | Count |
|---|---|---|
| Users & Auth | users, user_oauth_tokens, user_audible_accounts, user_preferences | 4 |
| Core Entities | books, authors, narrators, series, categories | 5 |
| Relationships | book_authors, book_narrators, book_series, book_categories | 4 |
| User Library | user_libraries, user_wishlists, user_reading_lists, user_reading_list_books | 4 |
| Pricing & Recs | book_prices, user_recommendations, price_alerts | 3 |
| Extended Data | book_extended_data | 1 |
| System | sync_jobs, user_analytics | 2 |
| **Audiblimey New** | goodreads_books, book_isbn_asin_map, import_jobs | 3 |
| **Total** | | **26** |

## Key PostgreSQL Conversion Patterns

1. **ENUM → CHECK**: All 5 ENUM usages need `VARCHAR + CHECK (col IN (...))` constraints
2. **ON UPDATE CURRENT_TIMESTAMP → Trigger**: Create a reusable `update_updated_at()` trigger function
3. **FULLTEXT → tsvector**: 2 FULLTEXT indexes on books table → tsvector columns with GIN indexes
4. **JSON → JSONB**: 15+ JSON columns → JSONB for indexable storage
5. **Prefix indexes** `(col(100))` → Full column indexes (PostgreSQL doesn't support prefix length)
6. **AUTO_INCREMENT → BIGSERIAL**: All 26 tables use BIGSERIAL primary keys
7. **pgvector**: Add `vector(1536)` column to books table for OpenAI text-embedding-3-small embeddings
