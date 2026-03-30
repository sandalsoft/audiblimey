-- Taste profiles: stores per-user taste vector (centroid of rated book embeddings)
-- and LLM-generated taste profile text.

CREATE TABLE taste_profiles (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    taste_vector vector(1536),
    profile_text TEXT,
    profile_edited TEXT,
    books_included INTEGER DEFAULT 0,
    generated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id)
);

CREATE INDEX idx_taste_profiles_user ON taste_profiles (user_id);
CREATE INDEX idx_taste_profiles_generated_at ON taste_profiles (generated_at);

CREATE TRIGGER trg_taste_profiles_updated_at
    BEFORE UPDATE ON taste_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
