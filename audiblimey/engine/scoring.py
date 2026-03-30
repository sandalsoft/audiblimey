"""Rating-weighted recommendation scoring engine for audiblimey.

Replaces AudiPy's hardcoded confidence scores (series=1.0, author=0.8, narrator=0.6)
with dynamic scoring that factors in:
- Goodreads ratings (average per author/narrator/series)
- Recency decay (exponential, half-life of 2 years)
- Negative signals (abandoned/DNF shelves)
- Series completion urgency
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from audiblimey.db import get_cursor

logger = logging.getLogger(__name__)

# Scoring weights (configurable)
WEIGHT_AUTHOR = 0.35
WEIGHT_NARRATOR = 0.25
WEIGHT_SERIES = 0.30
WEIGHT_NEGATIVE = -0.20  # Penalty weight

# Recency decay half-life in days (2 years)
RECENCY_HALF_LIFE_DAYS = 730


@dataclass
class ScoreComponent:
    """A single component of a recommendation score."""
    source: str  # 'author_rating', 'narrator_rating', 'series_progress', 'negative_signal'
    value: float
    weight: float
    detail: str
    
    @property
    def weighted_value(self) -> float:
        return self.value * self.weight


@dataclass
class RecommendationScore:
    """Complete score for a recommended book."""
    book_asin: str
    book_title: str = ""
    final_score: float = 0.0
    components: list[ScoreComponent] = field(default_factory=list)
    suggestion_type: str = ""
    source_name: str = ""
    
    def compute_final(self):
        """Compute final score from all components."""
        self.final_score = max(0.0, min(1.0, sum(c.weighted_value for c in self.components)))


def recency_decay(date_read: Optional[date], reference_date: Optional[date] = None) -> float:
    """Compute recency decay factor using exponential decay.
    
    Books read recently get weight ~1.0, books read years ago decay toward 0.
    Half-life: 2 years (a book read 2 years ago has weight 0.5).
    
    Args:
        date_read: When the book was read/finished
        reference_date: Reference date (defaults to today)
        
    Returns:
        Decay factor between 0.0 and 1.0
    """
    if not date_read:
        return 0.5  # Unknown date gets middle weight
    
    ref = reference_date or date.today()
    days_ago = (ref - date_read).days
    
    if days_ago <= 0:
        return 1.0
    
    # Exponential decay: e^(-λt) where λ = ln(2) / half_life
    decay_constant = math.log(2) / RECENCY_HALF_LIFE_DAYS
    return math.exp(-decay_constant * days_ago)


def get_author_scores(user_id: int = 1) -> dict[str, dict]:
    """Get rating-weighted scores for all authors in user's library.
    
    Returns dict of author_name → {avg_rating, book_count, weighted_score, books}
    """
    with get_cursor() as cur:
        cur.execute("""
            SELECT a.name, gb.my_rating, gb.date_read, gb.bookshelves, gb.title
            FROM goodreads_books gb
            JOIN book_isbn_asin_map m ON gb.id = m.goodreads_book_id
            JOIN books b ON m.asin = b.asin
            JOIN book_authors ba ON b.id = ba.book_id
            JOIN authors a ON ba.author_id = a.id
            WHERE gb.my_rating > 0
            ORDER BY a.name, gb.date_read DESC
        """)
        rows = cur.fetchall()
    
    authors = {}
    for name, rating, date_read, shelves, title in rows:
        if name not in authors:
            authors[name] = {"ratings": [], "books": [], "has_negative": False}
        
        decay = recency_decay(date_read)
        authors[name]["ratings"].append(float(rating) * decay)
        authors[name]["books"].append({
            "title": title,
            "rating": float(rating),
            "date_read": str(date_read) if date_read else None,
            "recency_decay": round(decay, 3),
        })
        
        # Check for negative shelf signals
        if shelves:
            shelf_lower = shelves.lower()
            if any(neg in shelf_lower for neg in ["abandoned", "dnf", "did-not-finish"]):
                authors[name]["has_negative"] = True
    
    # Compute weighted averages
    result = {}
    for name, data in authors.items():
        if data["ratings"]:
            avg = sum(data["ratings"]) / len(data["ratings"])
            result[name] = {
                "avg_rating": round(avg, 2),
                "book_count": len(data["ratings"]),
                "weighted_score": round(avg / 5.0, 4),  # Normalize to 0-1
                "has_negative": data["has_negative"],
                "books": data["books"],
            }
    
    return result


def get_narrator_scores(user_id: int = 1) -> dict[str, dict]:
    """Get rating-weighted scores for all narrators in user's library."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT n.name, gb.my_rating, gb.date_read, gb.title
            FROM goodreads_books gb
            JOIN book_isbn_asin_map m ON gb.id = m.goodreads_book_id
            JOIN books b ON m.asin = b.asin
            JOIN book_narrators bn ON b.id = bn.book_id
            JOIN narrators n ON bn.narrator_id = n.id
            WHERE gb.my_rating > 0
            ORDER BY n.name, gb.date_read DESC
        """)
        rows = cur.fetchall()
    
    narrators = {}
    for name, rating, date_read, title in rows:
        if name not in narrators:
            narrators[name] = {"ratings": [], "books": []}
        
        decay = recency_decay(date_read)
        narrators[name]["ratings"].append(float(rating) * decay)
        narrators[name]["books"].append({
            "title": title,
            "rating": float(rating),
            "date_read": str(date_read) if date_read else None,
        })
    
    result = {}
    for name, data in narrators.items():
        if data["ratings"]:
            avg = sum(data["ratings"]) / len(data["ratings"])
            result[name] = {
                "avg_rating": round(avg, 2),
                "book_count": len(data["ratings"]),
                "weighted_score": round(avg / 5.0, 4),
                "books": data["books"],
            }
    
    return result


def get_series_progress(user_id: int = 1) -> list[dict]:
    """Get incomplete series with urgency scoring.
    
    Returns series ordered by: progress * rating * urgency.
    """
    with get_cursor() as cur:
        cur.execute("""
            WITH user_series AS (
                SELECT 
                    s.id as series_id,
                    s.title as series_title,
                    COUNT(DISTINCT bs.book_id) as total_in_series,
                    COUNT(DISTINCT CASE WHEN ul.id IS NOT NULL THEN bs.book_id END) as owned_count,
                    MAX(bs.sequence) as max_owned_sequence,
                    AVG(CASE WHEN ul.user_rating IS NOT NULL THEN ul.user_rating END) as avg_audible_rating
                FROM series s
                JOIN book_series bs ON s.id = bs.series_id
                LEFT JOIN user_libraries ul ON bs.book_id = ul.book_id AND ul.user_id = %s
                GROUP BY s.id, s.title
                HAVING COUNT(DISTINCT CASE WHEN ul.id IS NOT NULL THEN bs.book_id END) > 0
            )
            SELECT series_title, total_in_series, owned_count, max_owned_sequence, avg_audible_rating
            FROM user_series
            WHERE owned_count < total_in_series
            ORDER BY (owned_count::float / NULLIF(total_in_series, 0)) * COALESCE(avg_audible_rating, 3.0) DESC
        """, (user_id,))
        rows = cur.fetchall()
    
    series_list = []
    for title, total, owned, max_seq, avg_rating in rows:
        progress = float(owned) / max(total, 1)
        rating_factor = float(avg_rating or 3.0) / 5.0
        urgency = progress * rating_factor
        
        series_list.append({
            "series_title": title,
            "total_books": total,
            "owned_count": owned,
            "progress_pct": round(progress * 100, 1),
            "next_sequence": float(max_seq or 0) + 1,
            "avg_rating": round(float(avg_rating or 0), 1),
            "urgency_score": round(urgency, 4),
        })
    
    return series_list


def get_negative_signals(user_id: int = 1) -> dict:
    """Get authors/narrators associated with abandoned/DNF books.
    
    Returns dict of author/narrator names → negative signal strength.
    """
    negatives = {"authors": {}, "narrators": {}}
    
    with get_cursor() as cur:
        # Find Goodreads books with negative shelves
        cur.execute("""
            SELECT gb.title, gb.author, gb.bookshelves
            FROM goodreads_books gb
            WHERE gb.bookshelves ILIKE ANY(ARRAY['%abandoned%', '%dnf%', '%did-not-finish%', '%gave-up%'])
        """)
        rows = cur.fetchall()
        
        for title, author, shelves in rows:
            if author:
                negatives["authors"][author] = negatives["authors"].get(author, 0) + 1
    
    return negatives


def score_recommendation(
    book_asin: str,
    book_title: str,
    suggestion_type: str,
    source_name: str,
    author_scores: dict,
    narrator_scores: dict,
    negative_signals: dict,
    series_progress: list,
) -> RecommendationScore:
    """Compute a rating-weighted score for a single recommendation.
    
    Args:
        book_asin: ASIN of the recommended book
        book_title: Title of the recommended book
        suggestion_type: 'author', 'narrator', 'series', or 'similar'
        source_name: Name of the triggering entity (author name, narrator name, etc.)
        author_scores: Author score data from get_author_scores()
        narrator_scores: Narrator score data from get_narrator_scores()
        negative_signals: Negative signal data from get_negative_signals()
        series_progress: Series progress data from get_series_progress()
        
    Returns:
        RecommendationScore with components and final score
    """
    score = RecommendationScore(
        book_asin=book_asin,
        book_title=book_title,
        suggestion_type=suggestion_type,
        source_name=source_name,
    )
    
    # Author score
    if source_name in author_scores:
        data = author_scores[source_name]
        score.components.append(ScoreComponent(
            source="author_rating",
            value=data["weighted_score"],
            weight=WEIGHT_AUTHOR,
            detail=f"Avg rating {data['avg_rating']}/5 across {data['book_count']} books by {source_name}",
        ))
    
    # Narrator score (look up narrator for this book)
    for narrator_name, ndata in narrator_scores.items():
        # Check if this narrator is associated with the recommended book
        with get_cursor() as cur:
            cur.execute("""
                SELECT 1 FROM books b
                JOIN book_narrators bn ON b.id = bn.book_id
                JOIN narrators n ON bn.narrator_id = n.id
                WHERE b.asin = %s AND n.name = %s
            """, (book_asin, narrator_name))
            if cur.fetchone():
                score.components.append(ScoreComponent(
                    source="narrator_rating",
                    value=ndata["weighted_score"],
                    weight=WEIGHT_NARRATOR,
                    detail=f"Narrator {narrator_name} rated {ndata['avg_rating']}/5 across {ndata['book_count']} books",
                ))
                break
    
    # Series score
    if suggestion_type == "series":
        for sp in series_progress:
            if sp["series_title"].lower() in source_name.lower() or source_name.lower() in sp["series_title"].lower():
                score.components.append(ScoreComponent(
                    source="series_progress",
                    value=sp["urgency_score"],
                    weight=WEIGHT_SERIES,
                    detail=f"Series '{sp['series_title']}': {sp['progress_pct']}% complete ({sp['owned_count']}/{sp['total_books']})",
                ))
                break
    
    # Negative signals
    neg_authors = negative_signals.get("authors", {})
    if source_name in neg_authors:
        penalty = min(neg_authors[source_name] * 0.3, 1.0)  # Cap at 1.0
        score.components.append(ScoreComponent(
            source="negative_signal",
            value=penalty,
            weight=WEIGHT_NEGATIVE,
            detail=f"You abandoned {neg_authors[source_name]} book(s) by {source_name}",
        ))
    
    # If no components, give a baseline score
    if not score.components:
        score.components.append(ScoreComponent(
            source="baseline",
            value=0.5,
            weight=0.5,
            detail="No personalized signals available; using baseline score",
        ))
    
    score.compute_final()
    return score
