"""Tests for the taste-grounded LLM recommendation ask route and its helpers.

The model is grounded in the user's rated books (with ratings) plus the prompt;
the LLM call is mocked. Engine helpers (prompt formatting, response parsing, error
wrapping) are pure and tested directly.
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from audiblimey.api.main import app
from audiblimey.engine.recommend_chat import (
    AskModelError,
    _wrap_model_error,
    format_ask_messages,
    parse_recommendations,
    run_ask,
)

client = TestClient(app)

MODULE = "audiblimey.api.routes.recommendations"

RATED = [
    {"title": "House of Suns", "author": "Alastair Reynolds", "rating": 5.0},
    {"title": "Blindsight", "author": "Peter Watts", "rating": 4.0},
]


# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------


class TestFormatAskMessages:
    def test_grounds_in_rated_books_and_prompt(self):
        messages = format_ask_messages("more like House of Suns", RATED, limit=6)
        system, user = messages[0]["content"], messages[1]["content"]
        assert "at most 6" in system
        assert "already appears in their rated list" in system
        assert "more like House of Suns" in user
        # The taste listing carries titles, authors, and ratings.
        assert "House of Suns" in user and "Alastair Reynolds" in user
        assert "5.0" in user and "Blindsight" in user


class TestParseRecommendations:
    def test_malformed_json_raises_controlled_error(self):
        with pytest.raises(ValueError, match="malformed JSON"):
            parse_recommendations("not json {", 8)

    def test_non_object_json_raises(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            parse_recommendations("[1, 2, 3]", 8)

    def test_parses_and_preserves_order(self):
        content = json.dumps({
            "text": "Three picks",
            "recommendations": [
                {"title": "Revelation Space", "author": "Alastair Reynolds", "reason": "hard SF"},
                {"title": "Pushing Ice", "author": "Alastair Reynolds", "reason": "big ideas"},
            ],
        })
        text, recs = parse_recommendations(content, 8)
        assert text == "Three picks"
        assert [r["title"] for r in recs] == ["Revelation Space", "Pushing Ice"]
        assert recs[0]["reason"] == "hard SF"

    def test_dedupes_by_title_and_caps_at_limit(self):
        content = json.dumps({
            "text": "",
            "recommendations": [
                {"title": "Dune", "author": "Herbert"},
                {"title": "dune", "author": "Herbert"},  # case-insensitive dupe
                {"title": "Hyperion", "author": "Simmons"},
                {"title": "Neuromancer", "author": "Gibson"},
            ],
        })
        _, recs = parse_recommendations(content, limit=2)
        assert [r["title"] for r in recs] == ["Dune", "Hyperion"]

    def test_type_guards_skip_or_coerce_bad_fields(self):
        # Non-string title is skipped; non-string author/reason coerce to "".
        content = json.dumps({
            "text": None,
            "recommendations": [
                {"title": ["not", "a", "string"], "author": "X"},          # skipped
                {"title": "Good Book", "author": {"weird": 1}, "reason": 5},  # coerced
            ],
        })
        text, recs = parse_recommendations(content, 8)
        assert text == ""
        assert len(recs) == 1
        assert recs[0]["title"] == "Good Book"
        assert recs[0]["author"] == "" and recs[0]["reason"] == ""

    def test_missing_recommendations_key(self):
        text, recs = parse_recommendations(json.dumps({"text": "hmm"}), 8)
        assert text == "hmm" and recs == []


class TestRunAsk:
    def _mock_client(self, content):
        mock_client = MagicMock()
        message = MagicMock()
        message.content = content
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        mock_client.chat.completions.create.return_value = response
        return mock_client

    def test_run_ask_returns_parsed(self):
        mock_client = self._mock_client(json.dumps({
            "text": "Picked one",
            "recommendations": [{"title": "Chasm City", "author": "Reynolds", "reason": "fits"}],
        }))
        text, recs = run_ask("anything", RATED, limit=8, client=mock_client)
        assert text == "Picked one"
        assert recs[0]["title"] == "Chasm City"
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["temperature"] == 0.7

    def test_missing_content_raises_valueerror(self):
        mock_client = MagicMock()
        response = MagicMock()
        response.choices = []
        mock_client.chat.completions.create.return_value = response
        with pytest.raises(ValueError, match="missing expected content"):
            run_ask("q", RATED, 8, client=mock_client)

    def test_openai_error_wrapped_as_ask_model_error(self):
        from openai import OpenAIError

        class _Boom(OpenAIError):
            pass

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _Boom("service down")
        with pytest.raises(AskModelError) as exc_info:
            run_ask("q", RATED, 8, client=mock_client)
        assert exc_info.value.auth is False


class TestWrapModelError:
    def test_non_openai_exception_returned_unchanged(self):
        boom = KeyError("our bug")
        assert _wrap_model_error(boom) is boom

    def test_openai_error_becomes_ask_model_error(self):
        from openai import OpenAIError

        wrapped = _wrap_model_error(OpenAIError("rate limited"))
        assert isinstance(wrapped, AskModelError)
        assert wrapped.auth is False


# ---------------------------------------------------------------------------
# Route: POST /api/recommendations/ask
# ---------------------------------------------------------------------------


@contextmanager
def fake_get_cursor(cursor):
    yield cursor


class TestAskValidation:
    def test_missing_prompt_returns_422(self):
        assert client.post("/api/recommendations/ask", json={}).status_code == 422

    def test_empty_prompt_returns_422(self):
        assert client.post("/api/recommendations/ask", json={"prompt": ""}).status_code == 422

    def test_whitespace_prompt_returns_422(self):
        assert client.post("/api/recommendations/ask", json={"prompt": "   "}).status_code == 422

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_api_key_returns_503(self):
        import os
        os.environ.pop("OPENAI_API_KEY", None)
        resp = client.post("/api/recommendations/ask", json={"prompt": "anything?"})
        assert resp.status_code == 503
        assert "OPENAI_API_KEY" in resp.json()["detail"]


class TestAskRoute:
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})
    def test_no_rated_books_returns_200_empty(self):
        with patch(f"{MODULE}._rated_books", return_value=[]), \
             patch(f"{MODULE}.run_ask") as mock_run:
            resp = client.post("/api/recommendations/ask", json={"prompt": "sci-fi please"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["rated_count"] == 0
        mock_run.assert_not_called()

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})
    def test_success_matches_catalog_and_hydrates(self):
        recs = [
            {"title": "Revelation Space", "author": "Alastair Reynolds", "reason": "hard SF you'd love"},
            {"title": "Obscure Title", "author": "Nobody", "reason": "a wildcard"},
        ]
        # Only the first recommendation exists in the catalog.
        catalog = {
            "revelation space": [
                {"asin": "B0REV", "image_url": "https://img/rev.jpg",
                 "authors": "Alastair Reynolds", "owned": True, "href": "/books/B0REV"}
            ]
        }
        with patch(f"{MODULE}._rated_books", return_value=RATED), \
             patch(f"{MODULE}.run_ask", return_value=("Two picks for you.", recs)), \
             patch(f"{MODULE}._match_catalog", return_value=catalog), \
             patch(f"{MODULE}._resolve_uncataloged", return_value={}):
            resp = client.post("/api/recommendations/ask", json={"prompt": "more Reynolds"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Two picks for you."
        assert data["rated_count"] == 2

        first, second = data["items"]
        assert first["title"] == "Revelation Space"
        assert first["asin"] == "B0REV"
        assert first["href"] == "/books/B0REV"
        assert first["owned"] is True
        assert first["image_url"] == "https://img/rev.jpg"
        assert first["reason"] == "hard SF you'd love"

        # Not in catalog and not resolved → no link, not owned.
        assert second["title"] == "Obscure Title"
        assert second["asin"] is None
        assert second["href"] is None
        assert second["owned"] is False

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})
    def test_uncataloged_recs_resolved_via_audible(self):
        recs = [{"title": "Revelation Space", "author": "Alastair Reynolds", "reason": "hard SF"}]
        resolved = {
            "revelation space": {
                "asin": "B0AUD", "image_url": "https://img/aud.jpg",
                "href": "/books/B0AUD", "owned": False,
            }
        }
        with patch(f"{MODULE}._rated_books", return_value=RATED), \
             patch(f"{MODULE}.run_ask", return_value=("One pick.", recs)), \
             patch(f"{MODULE}._match_catalog", return_value={}), \
             patch(f"{MODULE}._resolve_uncataloged", return_value=resolved) as mock_resolve:
            resp = client.post("/api/recommendations/ask", json={"prompt": "more Reynolds"})

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["asin"] == "B0AUD"
        assert item["href"] == "/books/B0AUD"
        assert item["image_url"] == "https://img/aud.jpg"
        assert item["owned"] is False
        # Only the uncataloged rec was handed to the resolver.
        assert [r["title"] for r in mock_resolve.call_args[0][0]] == ["Revelation Space"]

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})
    def test_malformed_model_output_returns_502(self):
        with patch(f"{MODULE}._rated_books", return_value=RATED), \
             patch(f"{MODULE}.run_ask", side_effect=ValueError("bad json")):
            resp = client.post("/api/recommendations/ask", json={"prompt": "x"})
        assert resp.status_code == 502

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})
    def test_invalid_key_returns_503(self):
        with patch(f"{MODULE}._rated_books", return_value=RATED), \
             patch(f"{MODULE}.run_ask", side_effect=AskModelError("bad key", auth=True)):
            resp = client.post("/api/recommendations/ask", json={"prompt": "x"})
        assert resp.status_code == 503

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})
    def test_model_outage_returns_502(self):
        with patch(f"{MODULE}._rated_books", return_value=RATED), \
             patch(f"{MODULE}.run_ask", side_effect=AskModelError("down", auth=False)):
            resp = client.post("/api/recommendations/ask", json={"prompt": "x"})
        assert resp.status_code == 502


class TestRatedBooksQuery:
    """The rated-books query selects genuinely-rated books, excluding the
    is_finished fallback (asserted structurally — FakeCursor can't run SQL)."""

    class _Cursor:
        def __init__(self, rows):
            self.rows = rows
            self.queries = []

        def execute(self, query, params=None):
            self.queries.append((query, params))

        def fetchall(self):
            return self.rows

        def close(self):
            pass

    def test_query_shape_and_mapping(self):
        from audiblimey.api.routes import recommendations as R

        cur = self._Cursor([("House of Suns", "Alastair Reynolds", 5.0)])
        with patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)):
            result = R._rated_books()
        assert result == [{"title": "House of Suns", "author": "Alastair Reynolds", "rating": 5.0}]
        sql = cur.queries[0][0]
        assert "user_manual_rating" in sql and "my_rating" in sql
        assert "t.rating > 0" in sql  # excludes unrated / is_finished fallback


class TestPickProduct:
    def _p(self, title, authors=()):
        return {"asin": "B0" + title[:3], "title": title,
                "authors": [{"name": n} for n in authors]}

    def test_exact_single_match(self):
        from audiblimey.api.routes.recommendations import _pick_product
        products = [self._p("Revelation Space", ["Alastair Reynolds"]), self._p("Other")]
        assert _pick_product(products, "Revelation Space", "Alastair Reynolds")["title"] == "Revelation Space"

    def test_no_exact_title_returns_none(self):
        from audiblimey.api.routes.recommendations import _pick_product
        # A close-but-not-equal title is rejected — exact match only.
        assert _pick_product([self._p("Revelation Space: Book 1")], "Revelation Space", "x") is None
        assert _pick_product([], "Anything", "x") is None

    def test_exact_title_links_even_if_author_differs(self):
        from audiblimey.api.routes.recommendations import _pick_product
        # Model mis-attributed the author; the title is the strong signal.
        p = _pick_product([self._p("Galileo's Dream", ["Kim Stanley Robinson"])],
                          "Galileo's Dream", "Alastair Reynolds")
        assert p["title"] == "Galileo's Dream"

    def test_disambiguates_multiple_exacts_by_author(self):
        from audiblimey.api.routes.recommendations import _pick_product
        products = [self._p("Eon", ["Wrong Author"]), self._p("Eon", ["Greg Bear"])]
        assert _pick_product(products, "Eon", "Greg Bear")["authors"][0]["name"] == "Greg Bear"


class TestResolveUncataloged:
    PRODUCT = {
        "asin": "B0REV", "title": "Revelation Space",
        "authors": [{"name": "Alastair Reynolds"}], "image_url": "https://img/rev.jpg",
    }
    RECS = [{"title": "Revelation Space", "author": "Alastair Reynolds", "reason": "r"}]

    def test_resolves_and_stores(self):
        from audiblimey.api.routes import recommendations as R
        cur = MagicMock()
        with patch(f"{MODULE}.client_from_db", return_value=object()), \
             patch(f"{MODULE}.search_catalog", return_value=[self.PRODUCT]), \
             patch(f"{MODULE}.store_book") as mock_store, \
             patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)):
            resolved = R._resolve_uncataloged(self.RECS)
        assert resolved == {
            "revelation space": {
                "asin": "B0REV", "image_url": "https://img/rev.jpg",
                "href": "/books/B0REV", "owned": False,
            }
        }
        mock_store.assert_called_once()
        assert mock_store.call_args.kwargs.get("in_library") is False or mock_store.call_args[0][-1] is False

    def test_missing_audible_auth_degrades_to_empty(self):
        from audiblimey.api.routes import recommendations as R
        with patch(f"{MODULE}.client_from_db", side_effect=RuntimeError("no auth")):
            assert R._resolve_uncataloged(self.RECS) == {}

    def test_no_confident_match_skipped(self):
        from audiblimey.api.routes import recommendations as R
        with patch(f"{MODULE}.client_from_db", return_value=object()), \
             patch(f"{MODULE}.search_catalog", return_value=[{"asin": "B0X", "title": "Different Book"}]), \
             patch(f"{MODULE}.store_book"), \
             patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(MagicMock())):
            assert R._resolve_uncataloged(self.RECS) == {}

    def test_empty_recs_no_client_call(self):
        from audiblimey.api.routes import recommendations as R
        with patch(f"{MODULE}.client_from_db") as mock_client:
            assert R._resolve_uncataloged([]) == {}
        mock_client.assert_not_called()
