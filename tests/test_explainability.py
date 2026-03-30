"""Tests for recommendation explainability layer."""

import pytest

from audiblimey.engine.scoring import RecommendationScore, ScoreComponent
from audiblimey.engine.explainability import (
    generate_explanation,
    generate_score_breakdown,
    generate_short_explanation,
)


@pytest.fixture
def sample_score():
    """Create a sample recommendation score with multiple components."""
    score = RecommendationScore(
        book_asin="B003ZWFO7E",
        book_title="The Way of Kings",
        suggestion_type="author",
        source_name="Brandon Sanderson",
    )
    score.components = [
        ScoreComponent(
            source="author_rating",
            value=0.9,
            weight=0.35,
            detail="Avg rating 4.5/5 across 8 books by Brandon Sanderson",
        ),
        ScoreComponent(
            source="narrator_rating",
            value=0.8,
            weight=0.25,
            detail="Narrator Michael Kramer rated 4.0/5 across 3 books",
        ),
    ]
    score.compute_final()
    return score


@pytest.fixture
def negative_score():
    """Create a score with negative signals."""
    score = RecommendationScore(
        book_asin="TEST",
        book_title="Risky Book",
        suggestion_type="author",
        source_name="Mediocre Author",
    )
    score.components = [
        ScoreComponent(
            source="author_rating",
            value=0.6,
            weight=0.35,
            detail="Avg rating 3.0/5 across 4 books by Mediocre Author",
        ),
        ScoreComponent(
            source="negative_signal",
            value=0.3,
            weight=-0.20,
            detail="You abandoned 1 book(s) by Mediocre Author",
        ),
    ]
    score.compute_final()
    return score


@pytest.fixture
def series_score():
    """Create a series continuation score."""
    score = RecommendationScore(
        book_asin="SERIES_BOOK",
        book_title="Book 4",
        suggestion_type="series",
        source_name="The Stormlight Archive",
    )
    score.components = [
        ScoreComponent(
            source="series_progress",
            value=0.75,
            weight=0.30,
            detail="Series 'The Stormlight Archive': 75.0% complete (3/4)",
        ),
    ]
    score.compute_final()
    return score


class TestGenerateExplanation:
    def test_includes_author_emoji(self, sample_score):
        explanation = generate_explanation(sample_score)
        assert "📚" in explanation
        assert "Brandon Sanderson" in explanation

    def test_includes_narrator_emoji(self, sample_score):
        explanation = generate_explanation(sample_score)
        assert "🎧" in explanation
        assert "Michael Kramer" in explanation

    def test_includes_negative_signal(self, negative_score):
        explanation = generate_explanation(negative_score)
        assert "⚠️" in explanation
        assert "abandoned" in explanation

    def test_includes_series_progress(self, series_score):
        explanation = generate_explanation(series_score)
        assert "📖" in explanation
        assert "75.0%" in explanation

    def test_empty_components(self):
        score = RecommendationScore(book_asin="EMPTY")
        explanation = generate_explanation(score)
        assert "No specific" in explanation


class TestGenerateScoreBreakdown:
    def test_has_all_fields(self, sample_score):
        breakdown = generate_score_breakdown(sample_score)
        assert "final_score" in breakdown
        assert "components" in breakdown
        assert "explanation" in breakdown
        assert "suggestion_type" in breakdown
        assert "source_name" in breakdown

    def test_components_structure(self, sample_score):
        breakdown = generate_score_breakdown(sample_score)
        for comp in breakdown["components"]:
            assert "source" in comp
            assert "raw_value" in comp
            assert "weight" in comp
            assert "weighted_value" in comp
            assert "detail" in comp

    def test_final_score_matches(self, sample_score):
        breakdown = generate_score_breakdown(sample_score)
        assert breakdown["final_score"] == round(sample_score.final_score, 4)

    def test_explanation_non_empty(self, sample_score):
        breakdown = generate_score_breakdown(sample_score)
        assert len(breakdown["explanation"]) > 0


class TestGenerateShortExplanation:
    def test_author_recommendation(self, sample_score):
        short = generate_short_explanation(sample_score)
        assert "Brandon Sanderson" in short

    def test_series_recommendation(self, series_score):
        short = generate_short_explanation(series_score)
        assert "series" in short.lower()

    def test_empty_components(self):
        score = RecommendationScore(book_asin="EMPTY")
        short = generate_short_explanation(score)
        assert short == "Recommended for you"

    def test_negative_only(self):
        """Score with only negative components should still produce output."""
        score = RecommendationScore(book_asin="NEG")
        score.components = [
            ScoreComponent(
                source="negative_signal", value=0.5, weight=-0.2, detail="Abandoned"
            ),
        ]
        score.compute_final()
        short = generate_short_explanation(score)
        assert short == "Recommended for you"  # No positive signal to explain
