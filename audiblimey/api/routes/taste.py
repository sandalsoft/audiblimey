"""Taste profile API routes for audiblimey."""

import logging
import os
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from audiblimey.db import get_cursor
from audiblimey.engine.taste import generate_taste_profile

logger = logging.getLogger(__name__)
router = APIRouter(tags=["taste"])

SCOPES = ("title", "author", "narrator", "category", "series")

# Per-scope entity-label lookup for GET /taste/rules.
_LABEL_SQL = {
    "title": "SELECT title FROM books WHERE id = tr.entity_id",
    "author": "SELECT name FROM authors WHERE id = tr.entity_id",
    "narrator": "SELECT name FROM narrators WHERE id = tr.entity_id",
    "category": "SELECT name FROM categories WHERE id = tr.entity_id",
    "series": "SELECT title FROM series WHERE id = tr.entity_id",
}

# Per-scope entity search for building exclusion rules (fixed SQL — never
# interpolate the table/column names). `category` maps to genres.
_ENTITY_SEARCH_SQL = {
    "author": "SELECT id, name AS label FROM authors WHERE name ILIKE %s ORDER BY name LIMIT %s",
    "category": "SELECT id, name AS label FROM categories WHERE name ILIKE %s ORDER BY name LIMIT %s",
    "series": "SELECT id, title AS label FROM series WHERE title ILIKE %s ORDER BY title LIMIT %s",
    "title": "SELECT id, title AS label FROM books WHERE title ILIKE %s ORDER BY title LIMIT %s",
}


class ProfileEditBody(BaseModel):
    """Request body for updating the user-edited taste profile."""

    profile_edited: str


class RuleBody(BaseModel):
    """Request body for upserting a taste rule."""

    scope: Literal["title", "author", "narrator", "category", "series"]
    entity_id: int
    mode: Literal["exclude", "include"] = "exclude"


@router.get("/taste/profile")
async def get_taste_profile():
    """Fetch the stored taste profile for the current user (user_id=1).

    Returns profile text, edited text, book count, generation timestamp,
    and whether a taste vector exists. Returns null fields if no profile
    has been generated yet.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT profile_text, profile_edited, books_included,
                   generated_at, taste_vector IS NOT NULL AS has_vector
            FROM taste_profiles
            WHERE user_id = %s
            """,
            (1,),
        )
        row = cur.fetchone()

    if not row:
        return {
            "profile_text": None,
            "profile_edited": None,
            "books_included": 0,
            "generated_at": None,
            "has_vector": False,
        }

    profile_text, profile_edited, books_included, generated_at, has_vector = row
    return {
        "profile_text": profile_text,
        "profile_edited": profile_edited,
        "books_included": books_included,
        "generated_at": generated_at.isoformat() if generated_at else None,
        "has_vector": bool(has_vector),
    }


@router.post("/taste/generate")
async def generate_taste():
    """Generate (or regenerate) the taste profile for the current user.

    Computes a rating-weighted taste vector and calls an LLM to write
    a natural-language profile of reading preferences. Returns 503 if
    OPENAI_API_KEY is missing, 400 if there are not enough rated books.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured. Cannot generate taste profile.",
        )

    try:
        with get_cursor() as cur:
            profile_text = generate_taste_profile(cur, user_id=1)
    except Exception as e:
        logger.error("Taste profile generation failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Taste profile generation failed: {e}",
        )

    if profile_text is None:
        raise HTTPException(
            status_code=400,
            detail="Not enough rated books with embeddings to generate a taste profile.",
        )

    # Re-read the stored row for books_included and generated_at
    with get_cursor() as cur:
        cur.execute(
            "SELECT books_included, generated_at FROM taste_profiles WHERE user_id = %s",
            (1,),
        )
        row = cur.fetchone()

    books_included = row[0] if row else 0
    generated_at = row[1].isoformat() if row and row[1] else None

    return {
        "profile_text": profile_text,
        "books_included": books_included,
        "generated_at": generated_at,
    }


@router.put("/taste/profile")
async def update_taste_profile(body: ProfileEditBody):
    """Save user edits to their taste profile.

    Accepts a JSON body with profile_edited text. Updates the profile_edited
    column and updated_at timestamp. Returns the saved edit and timestamp.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE taste_profiles
            SET profile_edited = %s, updated_at = NOW()
            WHERE user_id = %s
            RETURNING profile_edited, updated_at
            """,
            (body.profile_edited, 1),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="No taste profile exists yet. Generate one first.",
        )

    return {
        "profile_edited": row[0],
        "updated_at": row[1].isoformat() if row[1] else None,
    }


@router.get("/taste/rules")
async def get_taste_rules():
    """Return active taste rules grouped by scope, each with a resolved label."""
    user_id = 1
    label_branches = "\n".join(
        f"WHEN '{scope}' THEN ({sql})" for scope, sql in _LABEL_SQL.items()
    )
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT tr.id, tr.scope, tr.entity_id, tr.mode,
                   CASE tr.scope {label_branches} END AS label
            FROM taste_rules tr
            WHERE tr.user_id = %s
            ORDER BY tr.scope, label
            """,
            (user_id,),
        )
        rows = cur.fetchall()

    grouped: dict[str, list] = {scope: [] for scope in SCOPES}
    for rule_id, scope, entity_id, mode, label in rows:
        grouped[scope].append(
            {"id": rule_id, "entity_id": entity_id, "mode": mode, "label": label}
        )
    return grouped


@router.put("/taste/rules")
async def put_taste_rule(body: RuleBody):
    """Upsert a single taste rule. Idempotent: re-putting flips/keeps mode and
    always returns the rule's id and mode."""
    user_id = 1
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO taste_rules (user_id, scope, entity_id, mode)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, scope, entity_id) DO UPDATE SET
                mode = EXCLUDED.mode, updated_at = NOW()
            RETURNING id, mode
            """,
            (user_id, body.scope, body.entity_id, body.mode),
        )
        rule_id, mode = cur.fetchone()
    return {"id": rule_id, "scope": body.scope, "entity_id": body.entity_id, "mode": mode}


@router.delete("/taste/rules/{rule_id}")
async def delete_taste_rule(rule_id: int = Path(..., ge=1)):
    """Delete a taste rule (clears the override entirely)."""
    user_id = 1
    with get_cursor() as cur:
        cur.execute(
            "DELETE FROM taste_rules WHERE id = %s AND user_id = %s RETURNING id",
            (rule_id, user_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Taste rule {rule_id} not found")
    return {"deleted": rule_id}


@router.get("/taste/entities")
async def search_taste_entities(
    scope: Literal["author", "category", "series", "title"],
    q: str = "",
    limit: int = Query(10, ge=1),
):
    """Search entities by name to build exclusion rules.

    Returns {"results": [{"id", "label"}]}. `category` maps to genres. A trimmed
    query shorter than 2 characters returns no results; limit is capped at 20.
    An invalid scope is rejected with 422 by FastAPI validation.
    """
    term = q.strip()
    if len(term) < 2:
        return {"results": []}
    capped = min(limit, 20)
    with get_cursor() as cur:
        cur.execute(_ENTITY_SEARCH_SQL[scope], (f"%{term}%", capped))
        rows = cur.fetchall()
    return {"results": [{"id": rid, "label": label} for rid, label in rows]}
