"""Recommendation explainability layer for audiblimey.

Generates human-readable explanations for why each book was recommended,
based on the scoring components. Makes the recommendation engine transparent
and debuggable.
"""

from audiblimey.engine.scoring import RecommendationScore, ScoreComponent


def generate_explanation(score: RecommendationScore) -> str:
    """Generate a human-readable explanation for a recommendation.
    
    Args:
        score: The computed recommendation score with components
        
    Returns:
        Human-readable explanation string
    """
    if not score.components:
        return "No specific recommendation signals available."
    
    parts = []
    
    for component in sorted(score.components, key=lambda c: abs(c.weighted_value), reverse=True):
        if component.source == "author_rating":
            parts.append(f"📚 {component.detail}")
        elif component.source == "narrator_rating":
            parts.append(f"🎧 {component.detail}")
        elif component.source == "series_progress":
            parts.append(f"📖 {component.detail}")
        elif component.source == "negative_signal":
            parts.append(f"⚠️ {component.detail}")
        elif component.source == "baseline":
            parts.append(f"ℹ️ {component.detail}")
        else:
            parts.append(component.detail)
    
    return " · ".join(parts)


def generate_score_breakdown(score: RecommendationScore) -> dict:
    """Generate a structured score breakdown for API responses.
    
    Args:
        score: The computed recommendation score
        
    Returns:
        Dict with structured breakdown
    """
    return {
        "final_score": round(score.final_score, 4),
        "suggestion_type": score.suggestion_type,
        "source_name": score.source_name,
        "components": [
            {
                "source": c.source,
                "raw_value": round(c.value, 4),
                "weight": round(c.weight, 4),
                "weighted_value": round(c.weighted_value, 4),
                "detail": c.detail,
            }
            for c in score.components
        ],
        "explanation": generate_explanation(score),
    }


def generate_short_explanation(score: RecommendationScore) -> str:
    """Generate a one-line explanation suitable for compact UI display.
    
    Args:
        score: The computed recommendation score
        
    Returns:
        Short one-line explanation
    """
    if not score.components:
        return "Recommended for you"
    
    # Pick the strongest positive signal
    best = max(
        (c for c in score.components if c.weighted_value > 0),
        key=lambda c: c.weighted_value,
        default=None,
    )
    
    if not best:
        return "Recommended for you"
    
    if best.source == "author_rating":
        return f"You love books by {score.source_name}"
    elif best.source == "narrator_rating":
        return f"Performed by a narrator you enjoy"
    elif best.source == "series_progress":
        return f"Continue your series"
    else:
        return f"Matches your taste profile"
