"""Audible OAuth authentication routes.

Two-step external browser flow:
1. POST /auth/audible/start — generates Amazon OAuth URL
2. POST /auth/audible/complete — exchanges redirect URL for tokens
3. GET  /auth/audible/status — checks if account is linked
"""

import json
import logging
import secrets
import time
from typing import Optional
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from audible import Authenticator
from audible.localization import Locale
from audible.login import build_oauth_url, create_code_verifier
from audible.register import register

from audiblimey.db import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

# Ephemeral storage for in-flight OAuth sessions (code_verifier + serial).
# TTL enforced at lookup time. Good enough for single-user local tool.
_pending_sessions: dict[str, dict] = {}
_SESSION_TTL_SECONDS = 600  # 10 minutes


class CompleteRequest(BaseModel):
    session_id: str
    response_url: str


@router.post("/auth/audible/start")
async def start_audible_auth(marketplace: str = "us"):
    """Generate an Amazon OAuth URL for Audible authentication.

    Returns the URL the user must open in their browser and a session_id
    to pass back when completing the flow.
    """
    locale = Locale(marketplace)
    code_verifier = create_code_verifier()

    oauth_url, serial = build_oauth_url(
        country_code=locale.country_code,
        domain=locale.domain,
        market_place_id=locale.market_place_id,
        code_verifier=code_verifier,
    )

    session_id = secrets.token_urlsafe(32)
    _pending_sessions[session_id] = {
        "code_verifier": code_verifier,
        "serial": serial,
        "domain": locale.domain,
        "marketplace": marketplace,
        "created_at": time.time(),
    }

    # Prune expired sessions while we're here
    now = time.time()
    expired = [k for k, v in _pending_sessions.items()
               if now - v["created_at"] > _SESSION_TTL_SECONDS]
    for k in expired:
        del _pending_sessions[k]

    logger.info("auth.start: generated OAuth URL for marketplace=%s", marketplace)

    return {"oauth_url": oauth_url, "session_id": session_id}


@router.post("/auth/audible/complete")
async def complete_audible_auth(body: CompleteRequest):
    """Complete the Audible OAuth flow.

    The user pastes the redirect URL from their browser after logging in.
    We extract the authorization code, register a device, and store the
    auth tokens in user_audible_accounts.
    """
    session = _pending_sessions.pop(body.session_id, None)
    if not session:
        raise HTTPException(400, "Invalid or expired session. Please start the auth flow again.")

    if time.time() - session["created_at"] > _SESSION_TTL_SECONDS:
        raise HTTPException(400, "Session expired. Please start the auth flow again.")

    # Parse the authorization code from the redirect URL
    try:
        parsed = httpx.URL(body.response_url)
        params = parse_qs(parsed.query.decode())
        authorization_code = params["openid.oa2.authorization_code"][0]
    except (KeyError, IndexError, Exception) as exc:
        raise HTTPException(
            400,
            "Could not extract authorization code from URL. "
            "Make sure you copied the full URL from the browser address bar.",
        ) from exc

    # Register the device with Amazon
    try:
        register_data = register(
            authorization_code=authorization_code,
            code_verifier=session["code_verifier"],
            domain=session["domain"],
            serial=session["serial"],
        )
    except Exception as exc:
        logger.error("auth.complete: device registration failed: %s", exc)
        raise HTTPException(500, f"Device registration failed: {exc}") from exc

    # Build an Authenticator to get the serialized auth dict
    auth = Authenticator()
    auth.locale = Locale(session["marketplace"])
    auth._update_attrs(**register_data)
    auth_data = json.dumps(auth.to_dict())

    # Upsert into user_audible_accounts
    user_id = 1
    marketplace = session["marketplace"]

    with get_cursor() as cur:
        # Check if a row already exists for this user
        cur.execute(
            "SELECT id FROM user_audible_accounts WHERE user_id = %s LIMIT 1",
            (user_id,),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE user_audible_accounts
                SET encrypted_auth_data = %s, marketplace = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (auth_data, marketplace, existing[0]),
            )
        else:
            cur.execute(
                """
                INSERT INTO user_audible_accounts (user_id, encrypted_auth_data, marketplace)
                VALUES (%s, %s, %s)
                """,
                (user_id, auth_data, marketplace),
            )

    logger.info("auth.complete: stored Audible auth for user_id=%d, marketplace=%s", user_id, marketplace)

    return {"status": "linked", "marketplace": marketplace}


@router.get("/auth/audible/status")
async def get_audible_auth_status():
    """Check whether an Audible account is linked for the current user."""
    user_id = 1

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT marketplace, updated_at, created_at
            FROM user_audible_accounts
            WHERE user_id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"linked": False}

    marketplace, updated_at, created_at = row
    return {
        "linked": True,
        "marketplace": marketplace,
        "linked_at": (updated_at or created_at).isoformat() if (updated_at or created_at) else None,
    }
