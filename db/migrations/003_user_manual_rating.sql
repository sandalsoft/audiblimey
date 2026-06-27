-- Personal one-click rating, distinct from user_libraries.user_rating
-- (which Audible sync overwrites with the public average rating).
-- 1.0–5.0 (integer stars stored as DECIMAL) or NULL when unrated.

ALTER TABLE user_libraries ADD COLUMN IF NOT EXISTS user_manual_rating DECIMAL(3,1);
