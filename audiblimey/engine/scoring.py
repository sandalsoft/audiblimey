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
from audiblimey.engine.taste import excluded_book_ids

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


# Per-owned-book affinity when the user has no personal star rating, derived
# from engagement: finishing a book is the strongest positive signal, an
# abandoned/untouched purchase the weakest. Used by author/narrator scoring.
_AFFINITY_FROM_ENGAGEMENT = """
    CASE WHEN ul.is_finished THEN 4.0
         WHEN ul.percent_complete > 50 THEN 3.5
         WHEN ul.percent_complete > 0 THEN 3.0
         ELSE 2.5 END
"""


def get_author_scores(user_id: int = 1, excluded_ids: Optional[set[int]] = None) -> dict[str, dict]:
    """Get affinity scores for all authors in the user's owned library.

    Affinity is driven by the signals the user actually has — purchases, finish
    rate, and personal ratings (``user_manual_rating`` when set, otherwise an
    engagement-derived score). Books excluded by taste rules do not contribute.

    Returns dict of author_name → {avg_rating, book_count, finished_count,
    weighted_score, has_negative, books}.
    """
    with get_cursor() as cur:
        if excluded_ids is None:
            excluded_ids = excluded_book_ids(cur, user_id)
        cur.execute(f"""
            SELECT a.name,
                   AVG(COALESCE(ul.user_manual_rating, {_AFFINITY_FROM_ENGAGEMENT})) AS affinity,
                   COUNT(*) AS book_count,
                   SUM(CASE WHEN ul.is_finished THEN 1 ELSE 0 END) AS finished_count
            FROM user_libraries ul
            JOIN book_authors ba ON ul.book_id = ba.book_id
            JOIN authors a ON ba.author_id = a.id
            WHERE ul.user_id = %s
              AND ul.book_id <> ALL(%s::bigint[])
            GROUP BY a.name
        """, (user_id, list(excluded_ids)))
        rows = cur.fetchall()

    result = {}
    for name, affinity, book_count, finished in rows:
        avg = float(affinity or 0)
        result[name] = {
            "avg_rating": round(avg, 2),
            "book_count": int(book_count),
            "finished_count": int(finished or 0),
            "weighted_score": round(min(avg / 5.0, 1.0), 4),
            "has_negative": False,
            "books": [],
        }

    return result


def get_narrator_scores(user_id: int = 1, excluded_ids: Optional[set[int]] = None) -> dict[str, dict]:
    """Get affinity scores for all narrators in the user's owned library.

    Mirrors :func:`get_author_scores` — driven by purchases, finish rate, and
    personal ratings. Books excluded by taste rules do not contribute.
    """
    with get_cursor() as cur:
        if excluded_ids is None:
            excluded_ids = excluded_book_ids(cur, user_id)
        cur.execute(f"""
            SELECT n.name,
                   AVG(COALESCE(ul.user_manual_rating, {_AFFINITY_FROM_ENGAGEMENT})) AS affinity,
                   COUNT(*) AS book_count,
                   SUM(CASE WHEN ul.is_finished THEN 1 ELSE 0 END) AS finished_count
            FROM user_libraries ul
            JOIN book_narrators bn ON ul.book_id = bn.book_id
            JOIN narrators n ON bn.narrator_id = n.id
            WHERE ul.user_id = %s
              AND ul.book_id <> ALL(%s::bigint[])
            GROUP BY n.name
        """, (user_id, list(excluded_ids)))
        rows = cur.fetchall()

    result = {}
    for name, affinity, book_count, finished in rows:
        avg = float(affinity or 0)
        result[name] = {
            "avg_rating": round(avg, 2),
            "book_count": int(book_count),
            "finished_count": int(finished or 0),
            "weighted_score": round(min(avg / 5.0, 1.0), 4),
            "books": [],
        }

    return result


def get_series_progress(user_id: int = 1, excluded_ids: Optional[set[int]] = None) -> list[dict]:
    """Get incomplete series with urgency scoring.

    Returns series ordered by: progress * rating * urgency. Books excluded by
    taste rules (incl. whole-series exclusions) do not count toward progress.
    """
    with get_cursor() as cur:
        if excluded_ids is None:
            excluded_ids = excluded_book_ids(cur, user_id)
        cur.execute("""
            WITH user_series AS (
                SELECT
                    s.id as series_id,
                    s.title as series_title,
                    COUNT(DISTINCT bs.book_id) as total_in_series,
                    COUNT(DISTINCT CASE WHEN ul.id IS NOT NULL THEN bs.book_id END) as owned_count,
                    MAX(bs.sequence) as max_owned_sequence,
                    AVG(COALESCE(ul.user_manual_rating, ul.user_rating)) as avg_audible_rating
                FROM series s
                JOIN book_series bs ON s.id = bs.series_id
                LEFT JOIN user_libraries ul ON bs.book_id = ul.book_id AND ul.user_id = %s
                WHERE bs.book_id <> ALL(%s::bigint[])
                GROUP BY s.id, s.title
                HAVING COUNT(DISTINCT CASE WHEN ul.id IS NOT NULL THEN bs.book_id END) > 0
            )
            SELECT series_id, series_title, total_in_series, owned_count, max_owned_sequence, avg_audible_rating
            FROM user_series
            WHERE owned_count < total_in_series
            ORDER BY (owned_count::float / NULLIF(total_in_series, 0)) * COALESCE(avg_audible_rating, 3.0) DESC
        """, (user_id, list(excluded_ids)))
        rows = cur.fetchall()

    series_list = []
    for series_id, title, total, owned, max_seq, avg_rating in rows:
        progress = float(owned) / max(total, 1)
        rating_factor = float(avg_rating or 3.0) / 5.0
        urgency = progress * rating_factor

        series_list.append({
            "series_id": series_id,
            "series_title": title,
            "total_books": total,
            "owned_count": owned,
            "progress_pct": round(progress * 100, 1),
            "next_sequence": float(max_seq or 0) + 1,
            "avg_rating": round(float(avg_rating or 0), 1),
            "urgency_score": round(urgency, 4),
        })
    
    return series_list


def get_negative_signals(user_id: int = 1, excluded_ids: Optional[set[int]] = None) -> dict:
    """Get authors/narrators associated with abandoned/DNF books.

    Returns dict of author/narrator names → negative signal strength. Books excluded
    by taste rules do not contribute (positive or negative).
    """
    negatives = {"authors": {}, "narrators": {}}

    with get_cursor() as cur:
        if excluded_ids is None:
            excluded_ids = excluded_book_ids(cur, user_id)
        # Find Goodreads books with negative shelves (%% escaped: query is parameterized)
        cur.execute("""
            SELECT gb.title, gb.author, gb.bookshelves
            FROM goodreads_books gb
            LEFT JOIN book_isbn_asin_map m ON m.goodreads_book_id = gb.id
            LEFT JOIN books b ON b.asin = m.asin
            WHERE gb.bookshelves ILIKE ANY(ARRAY['%%abandoned%%', '%%dnf%%', '%%did-not-finish%%', '%%gave-up%%'])
              AND (b.id IS NULL OR b.id <> ALL(%s::bigint[]))
        """, (list(excluded_ids),))
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
    book_narrators: Optional[list] = None,
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
    
    # Narrator score. Callers scoring many books should pass book_narrators (the
    # book's narrator names) to avoid a per-book DB hit; otherwise we look it up.
    if narrator_scores:
        if book_narrators is None:
            with get_cursor() as cur:
                cur.execute("""
                    SELECT n.name FROM books b
                    JOIN book_narrators bn ON b.id = bn.book_id
                    JOIN narrators n ON bn.narrator_id = n.id
                    WHERE b.asin = %s
                """, (book_asin,))
                book_narrators = [r[0] for r in cur.fetchall()]
        for narrator_name in book_narrators:
            ndata = narrator_scores.get(narrator_name)
            if ndata:
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
