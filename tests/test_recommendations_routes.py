"""Tests for recommendation API routes — taste-rule suppression across all surfaces.

Candidate/next-book suppression happens in SQL (the FakeCursor can't execute a WHERE),
so those are asserted structurally (the query carries the <> ALL clause + excluded param).
The detail route's exclusion is a Python check, so it is asserted behaviourally (404).
Behavioural suppression of the list/series surfaces is proven end-to-end against the DB.
"""

from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from audiblimey.api.main import app

client = TestClient(app)

MODULE = "audiblimey.api.routes.recommendations"


class RecCursor:
    """Records executed queries; returns configured rows by substring match."""

    def __init__(self, results=None):
        self.results = results or {}
        self.queries = []
        self._res = []

    def execute(self, query, params=None):
        self.queries.append((query.strip(), params))
        self._res = []
        for pattern, rows in self.results.items():
            if pattern in query:
                self._res = list(rows)
                return

    def fetchone(self):
        return self._res[0] if self._res else None

    def fetchall(self):
        return self._res

    def close(self):
        pass


@contextmanager
def fake_get_cursor(cursor):
    yield cursor


def _scoring_patches():
    """Stub the four source-signal helpers so routes run without a DB."""
    return [
        patch(f"{MODULE}.get_author_scores", return_value={}),
        patch(f"{MODULE}.get_narrator_scores", return_value={}),
        patch(f"{MODULE}.get_negative_signals", return_value={"authors": {}, "narrators": {}}),
        patch(f"{MODULE}.get_series_progress", return_value=[]),
    ]


class TestRecommendationSuppression:
    def test_candidate_query_carries_exclusion(self):
        cur = RecCursor({"FROM user_recommendations r": []})
        ps = _scoring_patches()
        with patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)), \
             patch(f"{MODULE}.excluded_book_ids", return_value={999}), \
             ps[0], ps[1], ps[2], ps[3]:
            resp = client.get("/api/recommendations")
        assert resp.status_code == 200
        cand = next((q, p) for q, p in cur.queries if "FROM user_recommendations r" in q)
        assert "<> ALL(%s::bigint[])" in cand[0]
        assert cand[1][0] == [999]  # excluded array is the first candidate-query param

    def test_candidate_query_suppresses_started_series(self):
        cur = RecCursor({"FROM user_recommendations r": []})
        ps = _scoring_patches()
        with patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)), \
             patch(f"{MODULE}.excluded_book_ids", return_value=set()), \
             ps[0], ps[1], ps[2], ps[3]:
            resp = client.get("/api/recommendations")
        assert resp.status_code == 200
        cand = next((q, p) for q, p in cur.queries if "FROM user_recommendations r" in q)
        # Candidates whose primary series is already started are dropped in SQL.
        assert "NOT EXISTS" in cand[0]
        assert "user_libraries ul2" in cand[0]

    def test_series_next_book_query_carries_exclusion(self):
        cur = RecCursor({"FROM book_series bs": []})
        series = [{
            "series_id": 1, "series_title": "S", "total_books": 3, "owned_count": 1,
            "progress_pct": 33.3, "next_sequence": 2, "avg_rating": 4.0, "urgency_score": 0.5,
        }]
        with patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)), \
             patch(f"{MODULE}.excluded_book_ids", return_value={999}), \
             patch(f"{MODULE}.get_series_progress", return_value=series):
            resp = client.get("/api/recommendations/series")
        assert resp.status_code == 200
        nb = next((q, p) for q, p in cur.queries if "FROM book_series bs" in q)
        assert "<> ALL(%s::bigint[])" in nb[0]
        assert nb[1][-1] == [999]  # excluded array is the last next-book param

    def test_detail_excluded_book_returns_404(self):
        # row: r.id, r.book_id, b.asin, b.title, b.subtitle, runtime, summary, language, stype, source, old_conf
        row = (1, 555, "B00X", "Title", None, 300, "summary", "en", "author", "Auth", 0.5)
        cur = RecCursor({"FROM user_recommendations r": [row]})
        with patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)), \
             patch(f"{MODULE}.excluded_book_ids", return_value={555}):
            resp = client.get("/api/recommendations/1")
        assert resp.status_code == 404

    def test_detail_missing_rec_returns_404(self):
        cur = RecCursor({})  # no row
        with patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)), \
             patch(f"{MODULE}.excluded_book_ids", return_value=set()):
            resp = client.get("/api/recommendations/12345")
        assert resp.status_code == 404


class TestRecommendationFeedPopulated:
    """Once candidate generation has populated user_recommendations, the read
    path returns scored, explained items and a resolved series next_book."""

    # Feed candidate row columns (19), in SELECT order:
    #   r.id, r.book_id, b.asin, b.title, runtime, stype, source, confidence,
    #   member, list, narrators, isbn, cached_image, matched_isbn,
    #   series_id, series_title, sequence, genre_id, genre_name
    def test_feed_returns_scored_item(self):
        row = (10, 555, "B0SERIES", "Mistborn 2", 600, "series", "Mistborn", 0.5,
               None, None, [], None, "https://img/cover.jpg", None,
               None, None, None, None, None)
        cur = RecCursor({"FROM user_recommendations r": [row]})
        series = [{
            "series_id": 9, "series_title": "Mistborn", "total_books": 3, "owned_count": 1,
            "progress_pct": 33.3, "next_sequence": 2, "avg_rating": 4.0, "urgency_score": 0.5,
        }]
        with patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)), \
             patch(f"{MODULE}.excluded_book_ids", return_value=set()), \
             patch(f"{MODULE}.get_author_scores", return_value={}), \
             patch(f"{MODULE}.get_narrator_scores", return_value={}), \
             patch(f"{MODULE}.get_negative_signals", return_value={"authors": {}, "narrators": {}}), \
             patch(f"{MODULE}.get_series_progress", return_value=series):
            resp = client.get("/api/recommendations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["type"] == "book"
        assert item["book"]["asin"] == "B0SERIES"
        assert item["book"]["image_url"] == "https://img/cover.jpg"
        assert item["suggestion_type"] == "series"
        assert item["score"] > 0
        assert item["explanation"]
        assert any(c["source"] == "series_progress" for c in item["score_breakdown"])

    def test_feed_image_url_isbn_fallback(self):
        # No cached cover, but an ISBN → OpenLibrary fallback URL.
        row = (10, 555, "B0X", "Book", 600, "author", "A", 0.5,
               None, None, [], "1234567890", None, None,
               None, None, None, None, None)
        cur = RecCursor({"FROM user_recommendations r": [row]})
        with patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)), \
             patch(f"{MODULE}.excluded_book_ids", return_value=set()), \
             patch(f"{MODULE}.get_author_scores", return_value={}), \
             patch(f"{MODULE}.get_narrator_scores", return_value={}), \
             patch(f"{MODULE}.get_negative_signals", return_value={"authors": {}, "narrators": {}}), \
             patch(f"{MODULE}.get_series_progress", return_value=[]):
            resp = client.get("/api/recommendations")
        item = resp.json()["items"][0]
        assert item["book"]["image_url"] == (
            "https://covers.openlibrary.org/b/isbn/1234567890-L.jpg?default=false"
        )

    def test_feed_groups_same_series(self):
        # Two unstarted candidates in one series collapse into a single series card.
        rows = [
            (10, 501, "B01", "Stormlight 1", 600, "author", "Sanderson", 0.6,
             None, None, [], None, "https://img/1.jpg", None,
             42, "Stormlight", 1.0, 9, "Fantasy"),
            (11, 502, "B02", "Stormlight 2", 600, "author", "Sanderson", 0.5,
             None, None, [], None, "https://img/2.jpg", None,
             42, "Stormlight", 2.0, 9, "Fantasy"),
        ]
        cur = RecCursor({"FROM user_recommendations r": rows})
        with patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)), \
             patch(f"{MODULE}.excluded_book_ids", return_value=set()), \
             patch(f"{MODULE}.get_author_scores", return_value={}), \
             patch(f"{MODULE}.get_narrator_scores", return_value={}), \
             patch(f"{MODULE}.get_negative_signals", return_value={"authors": {}, "narrators": {}}), \
             patch(f"{MODULE}.get_series_progress", return_value=[]):
            resp = client.get("/api/recommendations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["type"] == "series"
        assert item["series_id"] == 42
        assert item["series_title"] == "Stormlight"
        assert item["recommended_count"] == 2
        assert item["genre"]["name"] == "Fantasy"
        assert item["image_url"] == "https://img/1.jpg"  # lowest-sequence member cover
        assert len(item["books"]) == 2

    # Batched next-book row columns (12), in SELECT order:
    #   series_id, asin, title, runtime, sequence, isbn, cached_image,
    #   matched_isbn, genre_id, genre_name, member, list
    def test_series_next_book_is_resolved(self):
        next_row = (7, "B0NEXT", "Mistborn 3", 600, 3.0, None, "https://img/next.jpg",
                    None, 9, "Fantasy", None, None)
        cur = RecCursor({"FROM book_series bs": [next_row]})
        series = [{
            "series_id": 7, "series_title": "Mistborn", "total_books": 3, "owned_count": 2,
            "progress_pct": 66.6, "next_sequence": 3, "avg_rating": 4.0, "urgency_score": 0.66,
        }]
        with patch(f"{MODULE}.get_cursor", side_effect=lambda: fake_get_cursor(cur)), \
             patch(f"{MODULE}.excluded_book_ids", return_value=set()), \
             patch(f"{MODULE}.get_series_progress", return_value=series):
            resp = client.get("/api/recommendations/series")
        assert resp.status_code == 200
        s = resp.json()["series"][0]
        assert s["series_id"] == 7
        assert s["next_book"]["asin"] == "B0NEXT"
        assert s["next_book"]["sequence"] == 3.0
        assert s["next_book"]["image_url"] == "https://img/next.jpg"
        assert s["next_book"]["genre"]["name"] == "Fantasy"
