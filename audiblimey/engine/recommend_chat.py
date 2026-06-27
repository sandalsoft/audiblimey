"""LLM taste-based recommendations.

Ground the model in the books a single user has rated (with their ratings) plus a
free-text request, and ask it to recommend audiobooks they'd enjoy. Recommendations
come from the model's own knowledge — the route then best-effort matches each title
back to the catalog so owned/available books become clickable.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

ASK_MODEL = "gpt-4o-mini"
ASK_TEMPERATURE = 0.7
DEFAULT_ASK_LIMIT = 8
MAX_ASK_LIMIT = 12


class AskModelError(Exception):
    """The model call failed (auth / rate-limit / transport).

    Carries an ``auth`` flag so the route can distinguish a bad key (503) from a
    transient model outage (502) without importing the OpenAI error classes.
    """

    def __init__(self, message: str, *, auth: bool = False):
        super().__init__(message)
        self.auth = auth


def _get_openai_client():
    """Create OpenAI client, raising a clear error if the key is missing."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it before asking for recommendations."
        )
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def format_ask_messages(prompt: str, rated_books: list[dict], limit: int) -> list[dict]:
    """Build the chat messages: the taste grounding plus the user's request.

    ``rated_books`` is a list of ``{"title", "author", "rating"}`` ordered best-first.
    """
    system_msg = (
        "You are a personal audiobook recommender. You are given the books a single "
        "user has rated, with their star ratings (1-5) — this is their demonstrated "
        "taste. Using that taste together with the user's request, recommend "
        "audiobooks they would enjoy.\n"
        "Rules:\n"
        f"- Recommend at most {limit} titles, best first.\n"
        "- A recommendation must fit BOTH their demonstrated taste and their request.\n"
        "- Recommend real, specific books with the correct author for each.\n"
        "- Do NOT recommend any book that already appears in their rated list.\n"
        "- If their request can't be satisfied well, say so honestly and recommend "
        "fewer (or no) titles rather than padding.\n"
        'Respond with a JSON object: {"text": "<one to three sentences explaining your '
        'picks>", "recommendations": [{"title": "<book title>", "author": "<author>", '
        '"reason": "<one sentence tying it to their taste and request>"}]}'
    )
    taste_lines = "\n".join(
        f"- {b['rating']:.1f}★  {b['title']} — {b['author']}" if b.get("author")
        else f"- {b['rating']:.1f}★  {b['title']}"
        for b in rated_books
    )
    user_msg = (
        f"User request:\n{prompt}\n\n"
        f"Books the user has rated (rating, title, author):\n{taste_lines}"
    )
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def parse_recommendations(content: Optional[str], limit: int) -> tuple[str, list[dict]]:
    """Parse the model's JSON reply into (text, recommendations).

    Recommendations are de-duplicated by title and capped at ``limit``. Every field
    is type-guarded so a malformed entry is skipped, never crashing; malformed JSON
    raises ValueError so the caller can surface a controlled error.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Model returned malformed JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Model response was not a JSON object")

    text = data.get("text") or ""
    if not isinstance(text, str):
        text = str(text)

    raw = data.get("recommendations")
    if not isinstance(raw, list):
        raw = []

    recs: list[dict] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        key = title.strip().lower()
        if key in seen:
            continue
        seen.add(key)

        author = entry.get("author")
        author = author.strip() if isinstance(author, str) else ""
        reason = entry.get("reason")
        reason = reason.strip() if isinstance(reason, str) else ""

        recs.append({"title": title.strip(), "author": author, "reason": reason})
        if len(recs) >= limit:
            break

    return text.strip(), recs


def _wrap_model_error(exc: Exception) -> Exception:
    """Translate an OpenAI client error into a controlled AskModelError.

    Non-OpenAI exceptions (i.e. our own bugs) are returned unchanged so they keep
    propagating as a 500 rather than being masked.
    """
    try:
        from openai import AuthenticationError, OpenAIError
    except ImportError:
        return AskModelError(str(exc))

    if isinstance(exc, AuthenticationError):
        return AskModelError("OPENAI_API_KEY is invalid or expired.", auth=True)
    if isinstance(exc, OpenAIError):
        return AskModelError(f"The recommendation model is temporarily unavailable: {exc}")
    return exc


def run_ask(
    prompt: str, rated_books: list[dict], limit: int, client=None
) -> tuple[str, list[dict]]:
    """Call the LLM with the taste grounding and return (text, recommendations).

    Raises AskModelError on auth/transport failures and ValueError on missing or
    malformed model output.
    """
    if client is None:
        client = _get_openai_client()

    messages = format_ask_messages(prompt, rated_books, limit)
    try:
        response = client.chat.completions.create(
            model=ASK_MODEL,
            messages=messages,
            temperature=ASK_TEMPERATURE,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # noqa: BLE001 — translated to a controlled error below
        raise _wrap_model_error(exc) from exc

    if (
        not response.choices
        or not response.choices[0].message
        or response.choices[0].message.content is None
    ):
        raise ValueError("OpenAI response missing expected content")

    return parse_recommendations(response.choices[0].message.content, limit)
