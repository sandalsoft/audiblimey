"""Tests for recommendation candidate generation (engine/recommend.py)."""

from contextlib import contextmanager
from unittest.mock import patch

import audiblimey.engine.recommend as recommend


class FakeCursor:
    """Records executed SQL; returns owned ASINs and owned series titles.

    Matches by which source table the query reads: the owned-series query reads
    ``FROM series s``; the owned-ASINs query reads ``FROM user_libraries ul``.
    """

    def __init__(self, owned_asins=(), owned_series=()):
        self._owned = [(a,) for a in owned_asins]
        self._series = [(t,) for t in owned_series]
        self._results = []
        self.executed = []

    def execute(self, query, params=None):
        q = query.strip()
        self.executed.append((q, params))
        if "FROM series s" in q:
            self._results = self._series
        elif "FROM user_libraries ul" in q:
            self._results = self._owned
        else:
            self._results = []

    def fetchall(self):
        return self._results

    def fetchone(self):
        return self._results[0] if self._results else None

    def close(self):
        pass


def _run(owned_asins=(), owned_series=(), authors=None, narrators=None,
         series_products=None, catalog_products=None):
    cur = FakeCursor(owned_asins=owned_asins, owned_series=owned_series)

    @contextmanager
    def fake_get_cursor(*a, **k):
        yield cur

    book_id_counter = {"n": 100}

    def fake_store_book(c, user_id, product, in_library=True):
        assert in_library is False  # candidates must never be marked owned
        book_id_counter["n"] += 1
        return book_id_counter["n"]

    store_book_mock = patch.object(recommend, "store_book", side_effect=fake_store_book)

    with patch.object(recommend, "get_cursor", fake_get_cursor), \
         patch.object(recommend, "excluded_book_ids", return_value=set()), \
         patch.object(recommend, "get_author_scores", return_value=authors or {}), \
         patch.object(recommend, "get_narrator_scores", return_value=narrators or {}), \
         patch.object(recommend, "fetch_series_products", return_value=series_products or []), \
         patch.object(recommend, "search_catalog", return_value=catalog_products or []), \
         patch.object(recommend, "run_embedding_pipeline", return_value={}), \
         store_book_mock as sb:
        summary = recommend.generate_recommendations(user_id=1, client=object())
    return summary, cur, sb


def test_generates_candidates_from_series_and_authors():
    summary, cur, sb = _run(
        owned_series=["Mistborn"],
        authors={"Brandon Sanderson": {"weighted_score": 0.9, "book_count": 5}},
        series_products=[{"asin": "B100"}],
        catalog_products=[{"asin": "B200"}],
    )

    assert summary == {"candidates": 2, "authors": 1, "narrators": 0, "series": 1}
    assert sb.call_count == 2
    inserts = [q for q, _ in cur.executed if "INSERT INTO user_recommendations" in q]
    assert len(inserts) == 2


def test_owned_books_are_not_recommended():
    summary, _, sb = _run(
        owned_asins=["OWNED"],
        owned_series=["Mistborn"],
        series_products=[{"asin": "B100"}, {"asin": "OWNED"}],
    )

    assert summary["candidates"] == 1
    assert sb.call_count == 1


def test_strongest_source_wins_for_shared_book():
    # B100 is reachable via both series and author; series should win.
    summary, cur, _ = _run(
        owned_series=["Mistborn"],
        authors={"Brandon Sanderson": {"weighted_score": 0.9, "book_count": 5}},
        series_products=[{"asin": "B100"}],
        catalog_products=[{"asin": "B100"}],
    )

    assert summary["candidates"] == 1
    insert = next(p for q, p in cur.executed if "INSERT INTO user_recommendations" in q)
    # params = (user_id, book_id, suggestion_type, source_name)
    assert insert[2] == "series"
    assert insert[3] == "Mistborn"
