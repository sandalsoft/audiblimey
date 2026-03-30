"""Tests for Audible auth routes."""

import json
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from audiblimey.api.main import app
from audiblimey.api.routes.auth import _pending_sessions

client = TestClient(app)


class FakeCursor:
    """Mock cursor that dispatches results based on SQL query patterns."""

    def __init__(self, results=None):
        self._results = results or {}
        self._last_result = None

    def execute(self, query, params=None):
        query_lower = query.lower().strip()
        if "select" in query_lower and "user_audible_accounts" in query_lower:
            self._last_result = self._results.get("select_account")
        elif "update" in query_lower and "user_audible_accounts" in query_lower:
            self._last_result = None
        elif "insert" in query_lower and "user_audible_accounts" in query_lower:
            self._last_result = None
        else:
            self._last_result = None

    def fetchone(self):
        return self._last_result


class FakeCursorCtx:
    """Context manager wrapper for FakeCursor."""

    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        pass


# --- POST /api/auth/audible/start ---

class TestStartAuth:
    @patch("audiblimey.api.routes.auth.Locale")
    @patch("audiblimey.api.routes.auth.create_code_verifier")
    @patch("audiblimey.api.routes.auth.build_oauth_url")
    def test_returns_oauth_url_and_session_id(self, mock_build, mock_verifier, mock_locale):
        mock_locale.return_value = MagicMock(
            country_code="us", domain="com", market_place_id="AF2M0KC94RCEA"
        )
        mock_verifier.return_value = b"test_verifier"
        mock_build.return_value = ("https://amazon.com/oauth?code=abc", "serial-123")

        # Clear any leftover sessions
        _pending_sessions.clear()

        r = client.post("/api/auth/audible/start")
        assert r.status_code == 200
        data = r.json()
        assert "oauth_url" in data
        assert "session_id" in data
        assert data["oauth_url"] == "https://amazon.com/oauth?code=abc"
        assert data["session_id"] in _pending_sessions

    @patch("audiblimey.api.routes.auth.Locale")
    @patch("audiblimey.api.routes.auth.create_code_verifier")
    @patch("audiblimey.api.routes.auth.build_oauth_url")
    def test_stores_session_data(self, mock_build, mock_verifier, mock_locale):
        mock_locale.return_value = MagicMock(
            country_code="us", domain="com", market_place_id="AF2M0KC94RCEA"
        )
        mock_verifier.return_value = b"verifier_bytes"
        mock_build.return_value = ("https://example.com", "serial-456")

        _pending_sessions.clear()

        r = client.post("/api/auth/audible/start?marketplace=uk")
        data = r.json()
        session = _pending_sessions[data["session_id"]]
        assert session["code_verifier"] == b"verifier_bytes"
        assert session["serial"] == "serial-456"
        assert session["marketplace"] == "uk"


# --- POST /api/auth/audible/complete ---

class TestCompleteAuth:
    def test_invalid_session_returns_400(self):
        _pending_sessions.clear()
        r = client.post("/api/auth/audible/complete", json={
            "session_id": "nonexistent",
            "response_url": "https://example.com?openid.oa2.authorization_code=abc"
        })
        assert r.status_code == 400
        assert "expired" in r.json()["detail"].lower() or "invalid" in r.json()["detail"].lower()

    def test_bad_url_returns_400(self):
        import time
        _pending_sessions.clear()
        _pending_sessions["test-session"] = {
            "code_verifier": b"verifier",
            "serial": "serial-1",
            "domain": "com",
            "marketplace": "us",
            "created_at": time.time(),
        }
        r = client.post("/api/auth/audible/complete", json={
            "session_id": "test-session",
            "response_url": "https://example.com/no-auth-code"
        })
        assert r.status_code == 400
        assert "authorization code" in r.json()["detail"].lower()

    @patch("audiblimey.api.routes.auth.get_cursor")
    @patch("audiblimey.api.routes.auth.Authenticator")
    @patch("audiblimey.api.routes.auth.register")
    def test_successful_complete_stores_tokens(self, mock_register, mock_auth_cls, mock_cursor):
        import time
        _pending_sessions.clear()
        _pending_sessions["good-session"] = {
            "code_verifier": b"verifier",
            "serial": "serial-1",
            "domain": "com",
            "marketplace": "us",
            "created_at": time.time(),
        }

        # Mock register to return auth data
        mock_register.return_value = {"access_token": "test-token"}

        # Mock the Authenticator instance
        mock_auth = MagicMock()
        mock_auth.to_dict.return_value = {"access_token": "test-token", "locale_code": "us"}
        mock_auth_cls.return_value = mock_auth

        cursor = FakeCursor({"select_account": None})
        mock_cursor.return_value = FakeCursorCtx(cursor)

        response_url = "https://localhost/?openid.oa2.authorization_code=AUTH_CODE_XYZ&foo=bar"
        r = client.post("/api/auth/audible/complete", json={
            "session_id": "good-session",
            "response_url": response_url,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "linked"
        assert data["marketplace"] == "us"

        # Session should be consumed
        assert "good-session" not in _pending_sessions

        # Verify register was called with correct args
        mock_register.assert_called_once_with(
            authorization_code="AUTH_CODE_XYZ",
            code_verifier=b"verifier",
            domain="com",
            serial="serial-1",
        )


# --- GET /api/auth/audible/status ---

class TestAuthStatus:
    @patch("audiblimey.api.routes.auth.get_cursor")
    def test_not_linked(self, mock_cursor):
        cursor = FakeCursor({"select_account": None})
        mock_cursor.return_value = FakeCursorCtx(cursor)
        r = client.get("/api/auth/audible/status")
        assert r.status_code == 200
        assert r.json()["linked"] is False

    @patch("audiblimey.api.routes.auth.get_cursor")
    def test_linked(self, mock_cursor):
        from datetime import datetime, timezone
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        cursor = FakeCursor({"select_account": ("us", now, now)})
        mock_cursor.return_value = FakeCursorCtx(cursor)
        r = client.get("/api/auth/audible/status")
        assert r.status_code == 200
        data = r.json()
        assert data["linked"] is True
        assert data["marketplace"] == "us"
