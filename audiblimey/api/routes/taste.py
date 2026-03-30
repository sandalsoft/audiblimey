"""Taste profile API routes for audiblimey."""

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from audiblimey.db import get_cursor
from audiblimey.engine.taste import generate_taste_profile

logger = logging.getLogger(__name__)
router = APIRouter(tags=["taste"])


class ProfileEditBody(BaseModel):
    """Request body for updating the user-edited taste profile."""

    profile_edited: str


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
