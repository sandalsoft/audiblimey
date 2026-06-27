"""Tests for Audible product-page enrichment."""

from unittest.mock import patch

from audiblimey.sync.enrich import (
    _sanitize_audible_html,
    fetch_book_enrichment,
    store_book_enrichment,
)


class StubClient:
    def __init__(self):
        self.calls = []

    def get(self, path, **params):
        self.calls.append((path, params))
        if path.endswith("/reviews"):
            return {
                "customer_reviews": [
                    {
                        "author_name": "Lesley",
                        "title": "More characters-a superior novel!",
                        "body": "A helpful review.",
                        "submission_date": "2024-01-02",
                        "ratings": {
                            "overall_rating": 5,
                            "performance_rating": 4,
                            "story_rating": 5,
                        },
                        "review_content_scores": {"num_helpful_votes": 11},
                    }
                ]
            }
        if path.endswith("/sims"):
            return {
                "similar_products": [
                    {
                        "asin": "REL1",
                        "title": "Related Book",
                        "authors": [{"name": "A. Writer"}],
                        "product_images": {"500": "https://cdn.example.com/rel.jpg"},
                    }
                ]
            }
        return {
            "product": {
                "publisher_summary": "<p>Full description</p><script>bad()</script>",
                "editorial_reviews": [{"body": "<p onclick=\"bad()\">Critic review</p>"}],
                "rating": {
                    "overall_distribution": {"display_average_rating": "4.0", "num_ratings": "1,234"},
                    "performance_distribution": {"display_average_rating": "4.4", "num_ratings": 900},
                    "story_distribution": {"display_average_rating": "4.3", "num_ratings": 850},
                },
                "category_ladders": [
                    {
                        "ladder": [
                            {"id": "1", "name": "Mysteries & Thrillers"},
                            {"id": "2", "name": "Espionage"},
                            {"id": "3", "name": "Spies & Politics"},
                        ]
                    },
                    {"ladder": [{"id": "4", "name": "Espionage"}]},
                ],
            }
        }


class FakeCursor:
    def __init__(self):
        self.executed = []
        self._result = None
        self._category_id = 10

    def execute(self, query, params=None):
        q = query.strip()
        self.executed.append((q, params))
        if "INTO categories" in q and "RETURNING id" in q:
            self._category_id += 1
            self._result = (self._category_id,)
        else:
            self._result = None

    def fetchone(self):
        return self._result


def test_fetch_book_enrichment_normalizes_audible_payloads():
    client = StubClient()

    data = fetch_book_enrichment(client, "B002V5GO3O")

    assert "<p>Full description</p>" in data["full_description"]
    assert "<script" not in data["full_description"]
    assert data["tags"] == ["Mysteries & Thrillers", "Espionage", "Spies & Politics"]
    assert data["ratings"]["overall"] == {"avg": 4.0, "count": 1234}
    assert data["ratings"]["performance"] == {"avg": 4.4, "count": 900}
    assert data["ratings"]["story"] == {"avg": 4.3, "count": 850}
    assert data["editorial_reviews"] == ["<p>Critic review</p>"]
    assert data["user_reviews"][0]["author"] == "Lesley"
    assert data["user_reviews"][0]["helpful_votes"] == 11
    assert data["related"][0]["asin"] == "REL1"

    review_call = next(call for call in client.calls if call[0].endswith("/reviews"))
    assert review_call[1]["sort_by"] == "MostHelpful"
    assert review_call[1]["num_results"] == 10


def test_sanitize_audible_html_strips_xss_bypass_payloads():
    cleaned = _sanitize_audible_html(
        '<p>Safe text</p>'
        '<a href=javascript:alert(1)>click</a>'
        '<iframe src="//evil.example/x">'
        '<img src=//tracker.example/pixel.gif>'
    )

    assert cleaned is not None
    assert "Safe text" in cleaned
    assert "javascript:" not in cleaned
    assert "<iframe" not in cleaned.lower()
    assert "<img" not in cleaned.lower()
    assert "tracker.example" not in cleaned


def test_fetch_book_enrichment_survives_failed_reviews_and_sims():
    class PartialClient:
        def get(self, path, **params):
            if path.endswith("/reviews") or path.endswith("/sims"):
                raise RuntimeError("Audible temporarily unavailable")
            return {
                "product": {
                    "publisher_summary": "<p>Full description</p>",
                    "rating": {
                        "overall_distribution": {
                            "display_average_rating": "4.5",
                            "num_ratings": 10,
                        }
                    },
                }
            }

    data = fetch_book_enrichment(PartialClient(), "B002V5GO3O")

    # Product details/ratings survive even though reviews + sims both failed.
    assert data["full_description"] == "<p>Full description</p>"
    assert data["ratings"]["overall"] == {"avg": 4.5, "count": 10}
    assert data["user_reviews"] == []
    assert data["related"] == []


def test_store_book_enrichment_writes_cache_categories_and_related_books():
    cur = FakeCursor()
    data = {
        "full_description": "<p>Full description</p>",
        "tags": ["Mysteries & Thrillers", "Espionage"],
        "categories": [
            {
                "audible_category_id": "1",
                "name": "Mysteries & Thrillers",
                "parent_name": None,
                "level": 0,
                "full_path": "Mysteries & Thrillers",
            },
            {
                "audible_category_id": "2",
                "name": "Espionage",
                "parent_name": "Mysteries & Thrillers",
                "level": 1,
                "full_path": "Mysteries & Thrillers > Espionage",
            },
        ],
        "ratings": {
            "overall": {"avg": 4.0, "count": 1234},
            "performance": {"avg": 4.4, "count": 900},
            "story": {"avg": 4.3, "count": 850},
        },
        "editorial_reviews": ["<p>Critic review</p>"],
        "user_reviews": [{"author": "Lesley", "helpful_votes": 11}],
        "related": [
            {
                "asin": "REL1",
                "title": "Related Book",
                "authors": [{"name": "A. Writer"}],
                "product_images": {"500": "https://cdn.example.com/rel.jpg"},
            }
        ],
    }

    with patch("audiblimey.sync.enrich.store_book", return_value=99) as store_book:
        store_book_enrichment(cur, 1, 42, "B002V5GO3O", data)

    store_book.assert_called_once()
    assert store_book.call_args.kwargs["in_library"] is False
    assert any("UPDATE books SET publisher_summary" in q for q, _ in cur.executed)
    assert any("DELETE FROM book_categories" in q for q, _ in cur.executed)
    assert len([q for q, _ in cur.executed if "INTO categories" in q]) == 2
    cache_query = next(q for q, _ in cur.executed if "INTO book_extended_data" in q)
    assert "rating_overall" in cache_query
    assert "audible_enriched_at" in cache_query
