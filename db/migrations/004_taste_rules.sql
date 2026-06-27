-- Taste rules: per-user include/exclude overrides that shape taste generation,
-- the taste vector, and all recommendation surfaces.
--
-- scope = what the rule targets; entity_id is polymorphic:
--   'title'    -> books.id
--   'author'   -> authors.id
--   'narrator' -> narrators.id
--   'category' -> categories.id   (genres)
--   'series'   -> series.id
-- mode = 'exclude' (drop matching books) or 'include' (override a broader exclude).
-- Precedence (see engine.taste._is_excluded): a 'title' rule wins outright; otherwise
-- a book is excluded iff an entity rule excludes it AND no entity rule includes it.

CREATE TABLE IF NOT EXISTS taste_rules (
    id BIGSERIAL PRIMARY KEY,
    user_id   BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope     VARCHAR(10) NOT NULL CHECK (scope IN ('title','author','narrator','category','series')),
    entity_id BIGINT NOT NULL,
    mode      VARCHAR(8) NOT NULL DEFAULT 'exclude' CHECK (mode IN ('exclude','include')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, scope, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_taste_rules_user ON taste_rules (user_id);

CREATE TRIGGER trg_taste_rules_updated_at
    BEFORE UPDATE ON taste_rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
