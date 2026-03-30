-- Audiblimey Database Schema
-- PostgreSQL 16 + pgvector
-- Migrated from AudiPy MySQL schema (dbarkman/AudiPy)

-- =============================================================================
-- Extensions
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- for fuzzy text search

-- =============================================================================
-- Utility: updated_at trigger function
-- Replaces MySQL's ON UPDATE CURRENT_TIMESTAMP
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 1. Users & Authentication
-- =============================================================================

CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    oauth_provider VARCHAR(50) NOT NULL,
    oauth_provider_id VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    avatar_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_login TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE (oauth_provider, oauth_provider_id)
);

CREATE INDEX idx_users_provider ON users (oauth_provider);
CREATE INDEX idx_users_created_at ON users (created_at);
CREATE INDEX idx_users_active ON users (is_active);
CREATE INDEX idx_users_last_login ON users (last_login);

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- OAuth provider tokens
CREATE TABLE user_oauth_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at TIMESTAMPTZ,
    scope TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, provider)
);

CREATE INDEX idx_user_oauth_tokens_user_id ON user_oauth_tokens (user_id);
CREATE INDEX idx_user_oauth_tokens_expires_at ON user_oauth_tokens (token_expires_at);

CREATE TRIGGER trg_user_oauth_tokens_updated_at
    BEFORE UPDATE ON user_oauth_tokens
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Audible authentication tokens
CREATE TABLE user_audible_accounts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    encrypted_auth_data TEXT NOT NULL,
    marketplace VARCHAR(10) DEFAULT 'us',
    last_sync TIMESTAMPTZ,
    sync_status VARCHAR(20) DEFAULT 'pending'
        CHECK (sync_status IN ('pending', 'syncing', 'completed', 'failed')),
    sync_error TEXT,
    tokens_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_user_audible_accounts_user_marketplace ON user_audible_accounts (user_id, marketplace);
CREATE INDEX idx_user_audible_accounts_last_sync ON user_audible_accounts (last_sync);
CREATE INDEX idx_user_audible_accounts_expires_at ON user_audible_accounts (tokens_expires_at);

CREATE TRIGGER trg_user_audible_accounts_updated_at
    BEFORE UPDATE ON user_audible_accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- User preferences
CREATE TABLE user_preferences (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    max_price DECIMAL(10,2) DEFAULT 12.66,
    preferred_language VARCHAR(20) DEFAULT 'english',
    marketplace VARCHAR(10) DEFAULT 'us',
    currency VARCHAR(3) DEFAULT 'USD',
    notifications_enabled BOOLEAN DEFAULT TRUE,
    price_alert_enabled BOOLEAN DEFAULT TRUE,
    new_release_alerts BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id)
);

CREATE TRIGGER trg_user_preferences_updated_at
    BEFORE UPDATE ON user_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- 2. Core Book Entities
-- =============================================================================

CREATE TABLE books (
    id BIGSERIAL PRIMARY KEY,
    asin VARCHAR(20) UNIQUE NOT NULL,
    amazon_asin VARCHAR(20),
    title TEXT NOT NULL,
    subtitle TEXT,

    -- Publishing
    publisher_name VARCHAR(500),
    publication_datetime TIMESTAMPTZ,
    publication_name VARCHAR(500),
    issue_date DATE,
    release_date DATE,
    isbn VARCHAR(20),
    language VARCHAR(20),

    -- Content
    content_type VARCHAR(50),
    content_delivery_type VARCHAR(50),
    format_type VARCHAR(50),
    runtime_length_min INTEGER,

    -- Descriptions
    merchandising_summary TEXT,
    merchandising_description TEXT,
    extended_product_description TEXT,
    audible_editors_summary TEXT,
    publisher_summary TEXT,

    -- Status flags
    is_adult_product BOOLEAN DEFAULT FALSE,
    is_listenable BOOLEAN DEFAULT FALSE,
    is_purchasability_suppressed BOOLEAN DEFAULT FALSE,
    is_vvab BOOLEAN DEFAULT FALSE,
    has_children BOOLEAN DEFAULT FALSE,

    -- Media & Technical
    sku VARCHAR(50),
    sku_lite VARCHAR(50),

    -- pgvector: embedding for similarity search (OpenAI text-embedding-3-small = 1536 dims)
    embedding vector(1536),

    -- Full-text search
    search_vector tsvector,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_books_asin ON books (asin);
CREATE INDEX idx_books_title ON books USING gin (to_tsvector('english', title));
CREATE INDEX idx_books_language ON books (language);
CREATE INDEX idx_books_publisher ON books (publisher_name);
CREATE INDEX idx_books_release_date ON books (release_date);
CREATE INDEX idx_books_runtime ON books (runtime_length_min);
CREATE INDEX idx_books_search_vector ON books USING gin (search_vector);
CREATE INDEX idx_books_embedding ON books USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TRIGGER trg_books_updated_at
    BEFORE UPDATE ON books
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Auto-update search_vector on insert/update
CREATE OR REPLACE FUNCTION update_books_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector = to_tsvector('english',
        COALESCE(NEW.title, '') || ' ' ||
        COALESCE(NEW.subtitle, '') || ' ' ||
        COALESCE(NEW.merchandising_summary, '') || ' ' ||
        COALESCE(NEW.extended_product_description, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_books_search_vector
    BEFORE INSERT OR UPDATE OF title, subtitle, merchandising_summary, extended_product_description
    ON books
    FOR EACH ROW EXECUTE FUNCTION update_books_search_vector();

-- Authors
CREATE TABLE authors (
    id BIGSERIAL PRIMARY KEY,
    asin VARCHAR(20) UNIQUE,
    name VARCHAR(500) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_authors_name ON authors (name);
CREATE INDEX idx_authors_asin ON authors (asin);

CREATE TRIGGER trg_authors_updated_at
    BEFORE UPDATE ON authors
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Narrators
CREATE TABLE narrators (
    id BIGSERIAL PRIMARY KEY,
    asin VARCHAR(20) UNIQUE,
    name VARCHAR(500) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_narrators_name ON narrators (name);
CREATE INDEX idx_narrators_asin ON narrators (asin);

CREATE TRIGGER trg_narrators_updated_at
    BEFORE UPDATE ON narrators
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Series
CREATE TABLE series (
    id BIGSERIAL PRIMARY KEY,
    asin VARCHAR(20) UNIQUE,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_series_title ON series (title);
CREATE INDEX idx_series_asin ON series (asin);

CREATE TRIGGER trg_series_updated_at
    BEFORE UPDATE ON series
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Categories / Genres
CREATE TABLE categories (
    id BIGSERIAL PRIMARY KEY,
    audible_category_id VARCHAR(50),
    name VARCHAR(500) NOT NULL,
    parent_id BIGINT REFERENCES categories(id) ON DELETE SET NULL,
    level INTEGER DEFAULT 0,
    full_path TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_categories_name ON categories (name);
CREATE INDEX idx_categories_parent ON categories (parent_id);
CREATE INDEX idx_categories_level ON categories (level);

-- =============================================================================
-- 3. Relationship Tables
-- =============================================================================

CREATE TABLE book_authors (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    author_id BIGINT NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    role VARCHAR(100) DEFAULT 'author',
    display_order INTEGER DEFAULT 0,
    UNIQUE (book_id, author_id)
);

CREATE INDEX idx_book_authors_book ON book_authors (book_id);
CREATE INDEX idx_book_authors_author ON book_authors (author_id);

CREATE TABLE book_narrators (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    narrator_id BIGINT NOT NULL REFERENCES narrators(id) ON DELETE CASCADE,
    display_order INTEGER DEFAULT 0,
    UNIQUE (book_id, narrator_id)
);

CREATE INDEX idx_book_narrators_book ON book_narrators (book_id);
CREATE INDEX idx_book_narrators_narrator ON book_narrators (narrator_id);

CREATE TABLE book_series (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    series_id BIGINT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    sequence DECIMAL(10,2),
    sequence_display VARCHAR(20),
    UNIQUE (book_id, series_id)
);

CREATE INDEX idx_book_series_book ON book_series (book_id);
CREATE INDEX idx_book_series_series ON book_series (series_id);
CREATE INDEX idx_book_series_sequence ON book_series (sequence);

CREATE TABLE book_categories (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    category_id BIGINT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    UNIQUE (book_id, category_id)
);

CREATE INDEX idx_book_categories_book ON book_categories (book_id);
CREATE INDEX idx_book_categories_category ON book_categories (category_id);

-- =============================================================================
-- 4. User Library & Progress
-- =============================================================================

CREATE TABLE user_libraries (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,

    -- Purchase
    purchase_date TIMESTAMPTZ,
    order_id VARCHAR(100),
    order_item_id VARCHAR(100),

    -- Library status
    date_added TIMESTAMPTZ,
    is_pending BOOLEAN DEFAULT FALSE,
    is_preordered BOOLEAN DEFAULT FALSE,
    is_removable BOOLEAN DEFAULT FALSE,
    is_visible BOOLEAN DEFAULT TRUE,
    is_archived BOOLEAN DEFAULT FALSE,

    -- Listening progress
    percent_complete DECIMAL(5,2) DEFAULT 0.00,
    is_finished BOOLEAN DEFAULT FALSE,

    -- Download
    is_downloaded BOOLEAN DEFAULT FALSE,
    is_playable BOOLEAN DEFAULT FALSE,

    -- User actions
    is_in_wishlist BOOLEAN DEFAULT FALSE,
    user_rating DECIMAL(3,1),

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (user_id, book_id)
);

CREATE INDEX idx_user_libraries_user ON user_libraries (user_id);
CREATE INDEX idx_user_libraries_book ON user_libraries (book_id);
CREATE INDEX idx_user_libraries_purchase_date ON user_libraries (purchase_date);
CREATE INDEX idx_user_libraries_is_finished ON user_libraries (is_finished);
CREATE INDEX idx_user_libraries_percent_complete ON user_libraries (percent_complete);

CREATE TRIGGER trg_user_libraries_updated_at
    BEFORE UPDATE ON user_libraries
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Wishlists
CREATE TABLE user_wishlists (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    priority INTEGER DEFAULT 0,
    notes TEXT,
    added_date TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, book_id)
);

CREATE INDEX idx_user_wishlists_user ON user_wishlists (user_id);
CREATE INDEX idx_user_wishlists_priority ON user_wishlists (priority);
CREATE INDEX idx_user_wishlists_added_date ON user_wishlists (added_date);

-- Reading lists
CREATE TABLE user_reading_lists (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_public BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_user_reading_lists_user ON user_reading_lists (user_id);
CREATE INDEX idx_user_reading_lists_name ON user_reading_lists (name);

CREATE TRIGGER trg_user_reading_lists_updated_at
    BEFORE UPDATE ON user_reading_lists
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Books in reading lists
CREATE TABLE user_reading_list_books (
    id BIGSERIAL PRIMARY KEY,
    reading_list_id BIGINT NOT NULL REFERENCES user_reading_lists(id) ON DELETE CASCADE,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    position INTEGER DEFAULT 0,
    added_date TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (reading_list_id, book_id)
);

CREATE INDEX idx_user_reading_list_books_list ON user_reading_list_books (reading_list_id);
CREATE INDEX idx_user_reading_list_books_position ON user_reading_list_books (position);

-- =============================================================================
-- 5. Pricing & Recommendations
-- =============================================================================

CREATE TABLE book_prices (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    marketplace VARCHAR(10) NOT NULL,
    credit_price DECIMAL(10,2),
    list_price DECIMAL(10,2),
    member_price DECIMAL(10,2),
    currency_code VARCHAR(3) DEFAULT 'USD',
    price_date DATE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (book_id, marketplace, price_date)
);

CREATE INDEX idx_book_prices_book ON book_prices (book_id);
CREATE INDEX idx_book_prices_date ON book_prices (price_date);
CREATE INDEX idx_book_prices_member ON book_prices (member_price);

-- Recommendations
CREATE TABLE user_recommendations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    suggestion_type VARCHAR(20) NOT NULL
        CHECK (suggestion_type IN ('series', 'author', 'narrator', 'similar', 'embedding')),
    source_book_id BIGINT REFERENCES books(id) ON DELETE SET NULL,
    source_name VARCHAR(500),
    confidence_score DECIMAL(5,4) DEFAULT 0.5000,

    -- Audiblimey: rating-weighted scoring fields
    rating_weight DECIMAL(5,4),
    recency_factor DECIMAL(5,4),
    negative_adjustment DECIMAL(5,4),
    series_urgency DECIMAL(5,4),
    score_breakdown JSONB,
    explanation_text TEXT,

    purchase_method VARCHAR(10) DEFAULT 'credits'
        CHECK (purchase_method IN ('cash', 'credits')),
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    is_dismissed BOOLEAN DEFAULT FALSE,

    UNIQUE (user_id, book_id, suggestion_type, source_name)
);

CREATE INDEX idx_user_recommendations_user ON user_recommendations (user_id);
CREATE INDEX idx_user_recommendations_type ON user_recommendations (suggestion_type);
CREATE INDEX idx_user_recommendations_generated ON user_recommendations (generated_at);
CREATE INDEX idx_user_recommendations_confidence ON user_recommendations (confidence_score);

-- Price alerts
CREATE TABLE price_alerts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    target_price DECIMAL(10,2) NOT NULL,
    alert_type VARCHAR(20) DEFAULT 'below'
        CHECK (alert_type IN ('below', 'percentage_off')),
    percentage_threshold DECIMAL(5,2),
    is_active BOOLEAN DEFAULT TRUE,
    last_notified TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_price_alerts_user ON price_alerts (user_id);
CREATE INDEX idx_price_alerts_book ON price_alerts (book_id);
CREATE INDEX idx_price_alerts_target ON price_alerts (target_price);
CREATE INDEX idx_price_alerts_active ON price_alerts (is_active);

-- =============================================================================
-- 6. Extended Book Data
-- =============================================================================

CREATE TABLE book_extended_data (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,

    -- Social & Media
    product_images JSONB,
    social_media_images JSONB,
    rich_images JSONB,

    -- Review & Rating
    customer_reviews JSONB,
    goodreads_ratings JSONB,
    rating DECIMAL(3,1),

    -- Content flags
    is_ayce BOOLEAN DEFAULT FALSE,
    is_buyable BOOLEAN DEFAULT FALSE,
    is_preorderable BOOLEAN DEFAULT FALSE,
    is_prereleased BOOLEAN DEFAULT FALSE,
    is_released BOOLEAN DEFAULT FALSE,
    is_returnable BOOLEAN DEFAULT FALSE,
    is_searchable BOOLEAN DEFAULT FALSE,
    is_shared BOOLEAN DEFAULT FALSE,
    is_pdf_url_available BOOLEAN DEFAULT FALSE,
    is_ws4v_enabled BOOLEAN DEFAULT FALSE,
    is_ws4v_companion_asin_owned BOOLEAN DEFAULT FALSE,

    -- Dates
    date_first_available DATE,
    preorder_release_date DATE,
    new_episode_added_date DATE,
    product_site_launch_date DATE,

    -- IDs & References
    destination_asin VARCHAR(20),
    origin_asin VARCHAR(20),
    origin_id VARCHAR(50),
    origin_marketplace VARCHAR(10),
    origin_type VARCHAR(50),
    ws4v_companion_asin VARCHAR(20),

    -- Content Details
    copyright TEXT,
    content_level VARCHAR(50),
    content_rating VARCHAR(50),
    narration_accent VARCHAR(100),
    voice_description TEXT,

    -- Series & Episode
    episode_count INTEGER,
    episode_number INTEGER,
    episode_type VARCHAR(50),
    season_number INTEGER,
    part_number INTEGER,

    -- Technical
    available_codecs JSONB,
    ws4v_details JSONB,

    -- URLs
    product_page_url TEXT,
    sample_url TEXT,
    pdf_url TEXT,
    claim_code_url TEXT,
    image_url TEXT,

    -- Tags & Keywords
    book_tags JSONB,
    tags JSONB,
    thesaurus_subject_keywords JSONB,
    platinum_keywords JSONB,
    long_tail_topic_tags JSONB,
    spotlight_tags JSONB,

    -- Other
    generic_keyword VARCHAR(500),
    text_to_speech JSONB,
    read_along_support JSONB,
    collection_ids JSONB,
    subscription_asins JSONB,
    music_id VARCHAR(50),

    UNIQUE (book_id)
);

-- =============================================================================
-- 7. System & Analytics
-- =============================================================================

CREATE TABLE sync_jobs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_type VARCHAR(20) NOT NULL
        CHECK (job_type IN ('full_sync', 'library_sync', 'suggestions_sync')),
    status VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    books_processed INTEGER DEFAULT 0,
    books_added INTEGER DEFAULT 0,
    books_updated INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sync_jobs_user ON sync_jobs (user_id);
CREATE INDEX idx_sync_jobs_status ON sync_jobs (status);
CREATE INDEX idx_sync_jobs_created ON sync_jobs (created_at);

CREATE TABLE user_analytics (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action_type VARCHAR(50) NOT NULL,
    entity_type VARCHAR(50),
    entity_id BIGINT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_user_analytics_user ON user_analytics (user_id);
CREATE INDEX idx_user_analytics_action ON user_analytics (action_type);
CREATE INDEX idx_user_analytics_created ON user_analytics (created_at);

-- =============================================================================
-- 8. Audiblimey: Goodreads Integration (NEW)
-- =============================================================================

-- Raw Goodreads CSV import data
CREATE TABLE goodreads_books (
    id BIGSERIAL PRIMARY KEY,
    goodreads_book_id VARCHAR(20),
    title TEXT NOT NULL,
    author VARCHAR(500),
    additional_authors TEXT,
    isbn VARCHAR(20),
    isbn13 VARCHAR(20),
    my_rating INTEGER CHECK (my_rating BETWEEN 0 AND 5),
    average_rating DECIMAL(3,2),
    num_pages INTEGER,
    original_publication_year INTEGER,
    date_read DATE,
    date_added DATE,
    bookshelves TEXT,       -- comma-separated shelf names
    exclusive_shelf VARCHAR(100),  -- read, currently-reading, to-read
    my_review TEXT,
    import_batch_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_goodreads_books_isbn13 ON goodreads_books (isbn13);
CREATE INDEX idx_goodreads_books_isbn ON goodreads_books (isbn);
CREATE INDEX idx_goodreads_books_rating ON goodreads_books (my_rating);
CREATE INDEX idx_goodreads_books_title ON goodreads_books USING gin (to_tsvector('english', title));
CREATE INDEX idx_goodreads_books_batch ON goodreads_books (import_batch_id);

-- ISBN-to-ASIN bridge table
CREATE TABLE book_isbn_asin_map (
    id BIGSERIAL PRIMARY KEY,
    isbn13 VARCHAR(20),
    isbn VARCHAR(20),
    asin VARCHAR(20) REFERENCES books(asin) ON DELETE SET NULL,
    goodreads_book_id BIGINT REFERENCES goodreads_books(id) ON DELETE CASCADE,
    match_source VARCHAR(20) NOT NULL
        CHECK (match_source IN ('openlibrary', 'fuzzy_title', 'manual', 'isbn_direct')),
    confidence DECIMAL(3,2) DEFAULT 0.00,
    matched_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_isbn_asin_map_isbn13 ON book_isbn_asin_map (isbn13);
CREATE INDEX idx_isbn_asin_map_asin ON book_isbn_asin_map (asin);
CREATE INDEX idx_isbn_asin_map_source ON book_isbn_asin_map (match_source);

-- Import job tracking
CREATE TABLE import_jobs (
    id BIGSERIAL PRIMARY KEY,
    import_type VARCHAR(20) NOT NULL DEFAULT 'goodreads',
    file_hash VARCHAR(64),
    total_rows INTEGER DEFAULT 0,
    matched_count INTEGER DEFAULT 0,
    unmatched_count INTEGER DEFAULT 0,
    match_rate DECIMAL(5,2) DEFAULT 0.00,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_import_jobs_status ON import_jobs (status);
CREATE INDEX idx_import_jobs_type ON import_jobs (import_type);

-- =============================================================================
-- 9. Seed: Default single user for development
-- =============================================================================

INSERT INTO users (oauth_provider, oauth_provider_id, display_name)
VALUES ('local', '1', 'audiblimey');

INSERT INTO user_preferences (user_id, max_price)
VALUES (1, 12.66);
