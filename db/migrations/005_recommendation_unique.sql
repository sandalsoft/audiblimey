-- One recommendation row per (user, book) so candidate generation can upsert
-- idempotently. The book is recommended via a single strongest source; the
-- generator picks that source and ON CONFLICT refreshes suggestion_type /
-- source_name while preserving is_dismissed across re-syncs.
--
-- The pre-existing UNIQUE (user_id, book_id, suggestion_type, source_name) stays
-- in place; this adds the stricter per-book constraint used as the upsert target.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'user_recommendations_user_book_unique'
    ) THEN
        ALTER TABLE user_recommendations
            ADD CONSTRAINT user_recommendations_user_book_unique UNIQUE (user_id, book_id);
    END IF;
END$$;
