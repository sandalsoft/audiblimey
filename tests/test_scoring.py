"""Tests for rating-weighted scoring engine."""

import math
from datetime import date, timedelta

import pytest

from audiblimey.engine.scoring import (
    recency_decay,
    ScoreComponent,
    RecommendationScore,
    score_recommendation,
    get_author_scores,
    get_narrator_scores,
    get_negative_signals,
    get_series_progress,
    RECENCY_HALF_LIFE_DAYS,
)


class TestRecencyDecay:
    def test_today_is_one(self):
        assert recency_decay(date.today()) == 1.0

    def test_future_is_one(self):
        assert recency_decay(date.today() + timedelta(days=30)) == 1.0

    def test_two_years_is_half(self):
        two_years_ago = date.today() - timedelta(days=RECENCY_HALF_LIFE_DAYS)
        decay = recency_decay(two_years_ago)
        assert abs(decay - 0.5) < 0.01

    def test_four_years_is_quarter(self):
        four_years_ago = date.today() - timedelta(days=RECENCY_HALF_LIFE_DAYS * 2)
        decay = recency_decay(four_years_ago)
        assert abs(decay - 0.25) < 0.01

    def test_none_returns_half(self):
        assert recency_decay(None) == 0.5

    def test_monotonically_decreasing(self):
        d1 = recency_decay(date.today() - timedelta(days=100))
        d2 = recency_decay(date.today() - timedelta(days=200))
        d3 = recency_decay(date.today() - timedelta(days=300))
        assert d1 > d2 > d3


class TestScoreComponent:
    def test_weighted_value(self):
        c = ScoreComponent(source="test", value=0.8, weight=0.35, detail="test")
        assert abs(c.weighted_value - 0.28) < 0.001

    def test_zero_weight(self):
        c = ScoreComponent(source="test", value=0.8, weight=0.0, detail="test")
        assert c.weighted_value == 0.0


class TestRecommendationScore:
    def test_compute_final(self):
        score = RecommendationScore(book_asin="TEST", book_title="Test")
        score.components = [
            ScoreComponent(source="a", value=0.8, weight=0.35, detail=""),
            ScoreComponent(source="b", value=0.6, weight=0.25, detail=""),
        ]
        score.compute_final()
        expected = 0.8 * 0.35 + 0.6 * 0.25  # 0.28 + 0.15 = 0.43
        assert abs(score.final_score - expected) < 0.001

    def test_clamped_to_0_1(self):
        score = RecommendationScore(book_asin="TEST")
        score.components = [
            ScoreComponent(source="a", value=1.0, weight=1.0, detail=""),
            ScoreComponent(source="b", value=1.0, weight=1.0, detail=""),
        ]
        score.compute_final()
        assert score.final_score == 1.0

    def test_negative_clamped_to_zero(self):
        score = RecommendationScore(book_asin="TEST")
        score.components = [
            ScoreComponent(source="a", value=0.1, weight=0.1, detail=""),
            ScoreComponent(source="neg", value=1.0, weight=-0.5, detail=""),
        ]
        score.compute_final()
        assert score.final_score == 0.0

    def test_higher_rating_beats_more_books(self):
        """Core requirement: author with higher avg rating ranks above author with more books."""
        # Author A: 2 books, avg rating 4.5/5 = 0.9 score
        score_a = RecommendationScore(book_asin="A")
        score_a.components = [
            ScoreComponent(source="author_rating", value=0.9, weight=0.35, detail="2 books, avg 4.5"),
        ]
        score_a.compute_final()

        # Author B: 6 books, avg rating 3.0/5 = 0.6 score
        score_b = RecommendationScore(book_asin="B")
        score_b.components = [
            ScoreComponent(source="author_rating", value=0.6, weight=0.35, detail="6 books, avg 3.0"),
        ]
        score_b.compute_final()

        assert score_a.final_score > score_b.final_score


class TestIntegration:
    """Integration tests requiring running database with seed data."""

    @pytest.fixture(autouse=True)
    def check_db(self):
        try:
            from audiblimey.db import get_cursor
            with get_cursor() as cur:
                cur.execute("SELECT 1")
        except Exception:
            pytest.skip("Database not available")

    def test_get_author_scores(self):
        scores = get_author_scores()
        # Should have scores for authors with matched Goodreads books
        assert isinstance(scores, dict)
        for name, data in scores.items():
            assert "avg_rating" in data
            assert "book_count" in data
            assert "weighted_score" in data
            assert data["weighted_score"] >= 0
            assert data["weighted_score"] <= 1

    def test_get_narrator_scores(self):
        scores = get_narrator_scores()
        assert isinstance(scores, dict)

    def test_get_series_progress(self):
        progress = get_series_progress()
        assert isinstance(progress, list)
        for sp in progress:
            assert "series_title" in sp
            assert "urgency_score" in sp

    def test_get_negative_signals(self):
        signals = get_negative_signals()
        assert "authors" in signals
        assert "narrators" in signals
        # Should find our "Bad Author" from seed data
        if signals["authors"]:
            assert isinstance(list(signals["authors"].values())[0], int)

    def test_score_recommendation_with_data(self):
        author_scores = get_author_scores()
        narrator_scores = get_narrator_scores()
        negative_signals = get_negative_signals()
        series_progress = get_series_progress()
        
        # Score a recommendation for a book by a known author
        if author_scores:
            author_name = list(author_scores.keys())[0]
            score = score_recommendation(
                book_asin="TEST_ASIN",
                book_title="Test Book",
                suggestion_type="author",
                source_name=author_name,
                author_scores=author_scores,
                narrator_scores=narrator_scores,
                negative_signals=negative_signals,
                series_progress=series_progress,
            )
            assert score.final_score > 0
            assert len(score.components) >= 1
            assert any(c.source == "author_rating" for c in score.components)
