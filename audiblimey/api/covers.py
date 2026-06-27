"""Cover-image URL resolution shared by the library and recommendation routes.

Resolution chain: cached Audible URL → OpenLibrary by the book's ISBN →
OpenLibrary by a Goodreads-matched ISBN.
"""

import re


def openlibrary_cover_url(isbn: str | None) -> str | None:
    if not isbn:
        return None
    cleaned = re.sub(r"[^0-9Xx]", "", isbn)
    if not cleaned:
        return None
    return f"https://covers.openlibrary.org/b/isbn/{cleaned}-L.jpg?default=false"


def resolve_image_url(
    cached_url: str | None,
    isbn: str | None,
    matched_isbn: str | None,
) -> str | None:
    return cached_url or openlibrary_cover_url(isbn) or openlibrary_cover_url(matched_isbn)
