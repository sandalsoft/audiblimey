-- Audible product-page enrichment cache.

ALTER TABLE book_extended_data
    ADD COLUMN IF NOT EXISTS rating_overall NUMERIC(3,2),
    ADD COLUMN IF NOT EXISTS rating_overall_count INTEGER,
    ADD COLUMN IF NOT EXISTS rating_performance NUMERIC(3,2),
    ADD COLUMN IF NOT EXISTS rating_performance_count INTEGER,
    ADD COLUMN IF NOT EXISTS rating_story NUMERIC(3,2),
    ADD COLUMN IF NOT EXISTS rating_story_count INTEGER,
    ADD COLUMN IF NOT EXISTS editorial_reviews JSONB,
    ADD COLUMN IF NOT EXISTS audible_related JSONB,
    ADD COLUMN IF NOT EXISTS audible_enriched_at TIMESTAMPTZ;

-- Staleness is computed in Python on read (lazy refresh), not queried in SQL,
-- and there is no batch stale-refresh job — so no index on audible_enriched_at.
-- Categories are deduped by select-then-insert in enrich.py (matching
-- authors/narrators/series), so no unique index on categories.name is needed.
