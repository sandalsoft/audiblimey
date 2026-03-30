# 10x Analysis: Audiblimey Recommendation Engine
Session 2 | Date: 2026-03-29

## Context Since Session 1

Four blocking questions from Session 1 were answered:
- **Fork AudiPy** as the foundation (not clean-room)
- **Single-user tool** (personal recommendation engine, not SaaS)
- **LLM APIs** for embeddings (OpenAI text-embedding-3-small or similar)
- **Substantial Goodreads history** available (the fuel for taste modeling)

This session refines the strategy through the lens of those decisions. Single-user changes everything: no social features, no community, no multi-tenant auth overhead. All effort goes into recommendation quality for one person's 696+ book Audible library and their Goodreads rating history.

## Current Value (Updated)

AudiPy's recommendation engine (`phase4_generate_recommendations.py`, 668 lines) uses three strategies with static confidence scores:

| Strategy | Confidence | Method |
|----------|-----------|--------|
| Series continuation | 1.0 | Find missing books in owned series |
| Favorite authors | 0.8 | Top 5 authors by book count, search catalog |
| Trusted narrators | 0.6 | Top 5 narrators by book count, search catalog |

The engine queries Audible's catalog API (`1.0/catalog/products`) with author/narrator/series name, caps results at 50 per search, does two-layer duplicate detection (ASIN + title fuzzy match), and applies the $12.66 cash-vs-credit threshold for purchase method.

**What it gets right**: Series continuation is genuinely useful. Purchase optimization is smart. The schema captures 142 fields per book across 27 tables -- plenty of signal.

**What it misses**: "Top 5 by count" is a blunt instrument. An author you bought 6 books from but rated 2 stars each gets recommended over an author you bought 2 from and loved. No Goodreads data. No embeddings. No negative feedback. No mood/genre awareness. Confidence scores are hardcoded, not earned.

## The Question

**With a fork of AudiPy, a single user's full Audible library, substantial Goodreads ratings, and LLM API access -- what's the smallest set of changes that produces recommendations good enough to replace browsing Audible altogether?**

---

## Massive Opportunities

### 1. Goodreads-Audible Taste Fusion Engine
**What**: Import Goodreads CSV export (ratings, shelves, review text). Match Goodreads books to Audible ASINs via ISBN-to-ASIN mapping (Open Library API, Amazon Product Advertising API, or community databases like ISBNdb). Build a unified book identity that carries both "I own this on Audible" and "I rated this 4 stars on Goodreads." Use the merged dataset as the ground truth for all downstream recommendations.

**Why 10x**: Right now AudiPy treats all owned books equally. A book you rage-quit at chapter 3 carries the same weight as one you re-listened to four times. Goodreads ratings break that tie. For a single user with substantial history, this is hundreds of explicit preference signals that the current engine ignores completely.

**Technical detail**: Goodreads CSV export contains: Book Id, Title, Author, Additional Authors, ISBN, ISBN13, My Rating, Average Rating, Number of Pages, Original Publication Year, Date Read, Date Added, Bookshelves, My Review, and more. The ISBN/ISBN13 fields are the bridge to ASIN. Shelves like "favorites", "abandoned", "to-read" carry intent signals beyond the 1-5 rating.

**What it unlocks**: Rating-weighted author/narrator scoring (replace "top 5 by count" with "top 5 by average rating weighted by recency"). Shelf-based intent signals ("abandoned" = negative, "favorites" = strong positive, "to-read" = wishlist import). Review text as embedding input for taste modeling.

**Effort**: High. ISBN-to-ASIN mapping is the hard part. Expect ~70-80% match rate initially. Manual resolution UI for unmatched books adds polish.
**Risk**: Match rate might be lower for obscure titles. Audiobook-only titles won't exist in Goodreads. Mitigation: unmatched books still get Audible-only treatment; matched books get the enhanced taste signal.
**Score**: 🔥

### 2. Embedding-Powered Similarity Search
**What**: Generate vector embeddings for every book using a composite of: book description (merchandising_summary + extended_product_description from schema), Goodreads review text (user's own reviews where available), genre/category path (categories table has hierarchical full_path), and structured metadata (runtime, publication era, series membership). Store embeddings in a vector column (MySQL 9.0+ supports vector type, or add pgvector via a PostgreSQL sidecar, or use a lightweight vector store like ChromaDB or LanceDB). Build a user taste vector as the weighted centroid of their highest-rated books. Recommend by nearest-neighbor search against Audible catalog books not yet owned.

**Why 10x**: This is the jump from "more books by authors you know" to "books that feel like the ones you loved, by authors you've never heard of." The current engine can never recommend a debut author. Embeddings can. For a power listener with 696+ books, the taste vector is unusually rich -- most collaborative filtering systems work with users who've rated 10-20 items. This user has 50x that signal.

**Technical detail**: OpenAI text-embedding-3-small produces 1536-dim vectors at ~$0.02 per million tokens. For 696 books with ~500 word descriptions, that's roughly $0.007 to embed the entire library. Negligible cost. The expensive part is embedding the broader Audible catalog for similarity search -- but you can start with just the user's library + recommendations and expand incrementally.

**What it unlocks**: Cross-genre discovery. Mood-based filtering (embeddings capture thematic/tonal similarity that metadata can't). "Find me something like [specific book]" as a one-click action. Dynamic confidence scores based on vector distance rather than hardcoded 1.0/0.8/0.6.

**Effort**: Very High. Embedding pipeline, vector storage, similarity search, prompt engineering for composite embeddings, incremental catalog expansion.
**Risk**: Embedding quality depends on description quality. Audible descriptions are marketing copy, not literary analysis. Mitigation: supplement with Goodreads review text and category metadata to ground the embeddings in reader perception rather than publisher positioning.
**Score**: 🔥

### 3. The Taste Profile as a Living Document
**What**: Generate and maintain a human-readable taste profile using an LLM. Feed it the user's top-rated books, abandoned books, genre distribution, narrator preferences, and reading patterns. Produce a structured document: "You prefer fast-paced sci-fi and literary fiction with unreliable narrators. You avoid romance subplots and books over 20 hours. You have a strong narrator loyalty to [names]. You read more non-fiction in Q1 and fiction in summer." Use this profile as the system prompt context for all LLM-powered recommendation queries.

**Why 10x**: Every other recommendation feature treats preferences as implicit signals buried in data. A taste profile makes them explicit, inspectable, and correctable. The user can read it and say "actually, I've been wanting to branch into historical fiction" -- and that correction feeds back immediately. It turns the recommendation engine from a black box into a conversation partner.

**What it unlocks**: Explainable recommendations grounded in stated preferences. User correction of model assumptions. Natural language queries against the profile ("show me something outside my comfort zone"). Seasonal/mood-aware recommendations without explicit mood tagging.

**Effort**: Medium-High. LLM summarization of reading history, structured profile schema, profile regeneration on library changes, correction interface.
**Risk**: LLM hallucination in profile generation. Mitigation: ground the profile in verifiable data points (book titles, ratings, dates) and let the user edit.
**Score**: 🔥

---

## Medium Opportunities

### 1. Rating-Weighted Recommendation Scoring
**What**: Replace the hardcoded confidence scores (series=1.0, author=0.8, narrator=0.6) with dynamic scores that factor in: user's average rating for that author/narrator/series, recency of engagement, completion rate (percent_complete from user_libraries), and Goodreads shelf signals. An author you rated 4.5 average across 8 books gets a higher confidence than one you rated 3.0 across 12 books. A series you're 80% through gets higher urgency than one you read book 1 of three years ago.

**Why matters more than it seems**: The current "top 5 by count" approach surfaces prolific authors you've bought a lot from, regardless of whether you liked them. For a 696-book library, there's meaningful variance in how much the user enjoyed different authors. Rating weighting turns quantity into quality.

**Impact**: Immediately better recommendation ordering. No new data needed if Goodreads import is done -- ratings already exist. Even without Goodreads, the `user_rating` field in `user_libraries` can be populated from Audible's own rating data.
**Effort**: Medium. Modify `get_user_authors()`, `get_user_narrators()`, `get_user_series()` queries to join against ratings. Update `calculate_confidence_score()` to use dynamic inputs.
**Score**: 🔥

### 2. Natural Language Book Discovery
**What**: A search interface where the user types "a short sci-fi novel with a female narrator, something dark but not grimdark, under 12 hours" and gets results ranked by taste profile match. Implementation: LLM parses the query into structured filters (genre, mood, runtime range, narrator gender) + semantic intent. Filters narrow the candidate set from the Audible catalog. Embedding similarity ranks the remaining candidates. Taste profile adds a personal relevance boost.

**Why matters more than it seems**: Audible's category browsing is coarse (30 genres). The user's mental model of what they want is much richer. Natural language bridges that gap. For a single-user tool, the LLM can be prompted with the full taste profile for deeply personalized results.

**Impact**: Transforms "I don't know what to listen to" from a 30-minute browse into a 30-second query. The single-user context is an advantage here -- no need to generalize across users, the LLM has complete context about one person's taste.
**Effort**: Medium. Query parsing via LLM, metadata filtering against existing schema fields (runtime_length_min, categories, narrators), embedding search for semantic matching.
**Score**: 🔥

### 3. Narrator Affinity Scoring
**What**: Build a narrator preference model separate from book ratings. Cross-reference which narrators appear in the user's highest-rated books vs. lowest-rated. Surface narrator affinity as a recommendation signal: "This narrator appears in 4 of your top-20 rated books." Track narrator style attributes (from Audible metadata and user feedback): accent, pacing, character voice range, gender. Use narrator affinity as a tiebreaker when two books score similarly on content.

**Why matters more than it seems**: Audiobook narrator quality is the single biggest differentiator from print/ebook. A book you'd rate 4 stars in print becomes a 5 with the right narrator or a 2 with the wrong one. No existing platform treats narrator preference as a first-class signal. AudiPy already stores narrator relationships in `book_narrators` -- the data is there, just unused in scoring.

**Impact**: Prevents wasted credits on books with narrators the user dislikes. Surfaces hidden gems performed by favorite narrators in unexpected genres.
**Effort**: Medium. Rating correlation analysis between narrators and book ratings. New scoring factor in recommendation ranking.
**Score**: 👍

### 4. "Why This Book" Explainability Layer
**What**: Every recommendation ships with a human-readable explanation generated from its scoring components: "Recommended because: you rated 4 other books by this author an average of 4.3 stars. The narrator performed 2 of your top-10 books. This is book 4 in a series you're 3 books into. Embedding similarity to your taste profile: 87%."

**Why matters more than it seems**: For a single-user tool, explainability isn't a trust exercise (you trust yourself). It's a debugging tool. When a recommendation feels wrong, the explanation tells you why the engine made that call. That feedback loop -- "oh, it recommended this because of the narrator, but I actually didn't like that narrator" -- is how the user trains the system without formal feedback mechanisms.

**Impact**: Turns every recommendation into a two-way signal. The explanation itself becomes a correction surface.
**Effort**: Medium. Format existing scoring components as natural language. Add embedding distance as a visible metric.
**Score**: 👍

### 5. Incremental Catalog Expansion
**What**: Instead of only searching Audible's catalog API at recommendation time (which caps at 50 results per query and requires active API calls), build a local shadow catalog. Periodically crawl Audible's new releases, bestsellers, and genre pages. Store book metadata locally. Embed new books as they're discovered. This creates a growing pool of candidates for similarity search that isn't limited by API query constraints.

**Why matters more than it seems**: The current engine only finds books that match exact author/narrator/series name searches. It can never discover a book by a new author in a new series with an unfamiliar narrator -- even if the book is a perfect taste match. A local catalog with embeddings removes that constraint. The engine can recommend any book it's ever seen, not just ones connected to what you already own.

**Impact**: Unlocks true discovery. The recommendation engine's candidate pool grows from "books connected to your existing library" to "every book on Audible."
**Effort**: Medium-High. Audible web scraping or API crawling, incremental embedding pipeline, storage for catalog metadata + vectors.
**Score**: 👍

---

## Small Gems

### 1. Goodreads "Abandoned" Shelf as Anti-Recommendation
**What**: Parse the "abandoned", "dnf" (did not finish), or "gave-up" shelves from Goodreads import. Use these as strong negative signals. Never recommend books by authors the user abandoned. Downweight genres over-represented in abandoned books. Surface this in the taste profile: "You tend to abandon epic fantasy over 25 hours."
**Why powerful**: Negative signals are rarer and more informative than positive ones. One abandoned book tells you more about taste boundaries than five completed ones. The data is free -- it's already in the Goodreads export.
**Effort**: Low (once Goodreads import exists). Parse shelf names, flag negative shelves, add negative weight to scoring.
**Score**: 🔥

### 2. Dynamic Credit-vs-Cash with Personal Listening Velocity
**What**: Replace the static $12.66 threshold with a calculation based on the user's actual credit usage rate. If they burn through 2 credits/month and buy the 24-credit annual plan ($229.50 = $9.56/credit), the threshold drops. If they stockpile credits, the threshold rises. Show: "At your pace, this book costs $9.56 via credit or $11.99 cash. Cash is the better deal."
**Why powerful**: The $12.66 number assumes 3-credit packs. Different subscription tiers have different credit costs. Personalized thresholds save real money on every purchase.
**Effort**: Low. Pull subscription tier from Audible API or let user set it. Recalculate threshold. Update purchase_method logic in `store_recommendation()`.
**Score**: 👍

### 3. Series Completion Urgency Indicator
**What**: On the dashboard, rank incomplete series by urgency: "You're 5 of 7 books into [Series]. Book 6 is $7.99 (cash deal). Book 7 releases in 3 months." Show completion percentage, next book availability, and price. One-click to add next book.
**Why powerful**: AudiPy already has series tracking via `book_series` with sequence numbers. The data exists but is buried in the recommendations list alongside everything else. Surfacing incomplete series as a dedicated widget converts the highest-intent signal into the shortest path to action. The user doesn't need convincing to buy book 6 of a series they're 5 deep into.
**Effort**: Low. Query `book_series` for user's incomplete series, join against catalog for next book availability and price, render as dashboard card.
**Score**: 🔥

### 4. "Surprise Me" Button
**What**: One button that picks a random recommendation weighted by: high embedding similarity but low author/narrator/genre familiarity. It deliberately pushes outside the user's comfort zone but stays within taste boundaries. Shows the book with a one-line pitch and the taste profile connection.
**Why powerful**: Every recommendation engine has a filter bubble problem. A deliberate serendipity feature combats it. For a single user who knows their own taste well, the value is in controlled surprise -- "I'd never have searched for this, but it's actually exactly what I'd love." Once embeddings exist, this is trivial to implement.
**Effort**: Low (once embeddings exist). Random selection from high-similarity, low-familiarity quadrant.
**Score**: 👍

### 5. Listening History Timeline
**What**: A simple chronological view of books listened to, colored by rating. Spot patterns at a glance: clusters of genres, narrator streaks, rating trends over time. Not a full analytics dashboard -- just a single scrollable timeline.
**Why powerful**: The user's reading history tells a story they can't see in a list view. "I went through a thriller phase in 2023, then switched to non-fiction" is visible in seconds. It's the minimum viable version of the "Reading Life" dashboard from Session 1, shippable in a day.
**Effort**: Low. Query user_libraries by purchase_date, join book metadata, render as a colored timeline.
**Score**: 👍

---

## Recommended Priority

### Do Now (Foundation -- everything else depends on these)
1. **Goodreads CSV Import & ISBN-to-ASIN Matching** -- This is the single highest-leverage change. Every recommendation improvement downstream depends on having explicit taste signals. The CSV format is stable, user-controlled, and rich.
2. **Rating-Weighted Recommendation Scoring** -- Replace "top 5 by count" with "top N by rating-weighted score." Immediately improves recommendation quality using data that already exists (or will exist after Goodreads import).
3. **Goodreads "Abandoned" Shelf as Anti-Recommendation** -- Free negative signals from existing data. Ship alongside Goodreads import.
4. **Series Completion Urgency Indicator** -- Highest-intent recommendation, data already exists, just needs better surfacing.

### Do Next (The taste engine)
1. **Embedding Pipeline (Library First)** -- Embed the user's 696+ owned books using descriptions + Goodreads review text + category metadata. Build the taste vector as a rated-weighted centroid. This is the foundation for similarity search. Unlocks: "Find me something like [book]", dynamic confidence scores, cross-genre discovery.
2. **Taste Profile Document** -- LLM-generated, human-readable, user-correctable. Becomes the system prompt for all future LLM interactions. Unlocks: natural language search, explainable recommendations, seasonal/mood awareness.
3. **"Why This Book" Explainability** -- Makes every recommendation a learning opportunity. Critical for debugging the taste engine during development.

### Explore (Expand the horizon)
1. **Natural Language Book Discovery** -- Once embeddings and taste profile exist, this is the interface that ties them together. Risk: query parsing quality. Upside: makes the tool genuinely fun to use.
2. **Incremental Catalog Expansion** -- Breaks free from the API query constraint. Risk: scraping reliability, storage growth. Upside: true discovery of books outside the user's existing graph.
3. **Narrator Affinity Scoring** -- Audiobook-specific signal that no other platform leverages well. Risk: narrator data quality. Upside: prevents bad narrator experiences, a uniquely frustrating audiobook problem.

### Backlog (Good but not yet)
1. **Dynamic Credit-vs-Cash Thresholds** -- Small optimization, depends on knowing subscription tier
2. **"Surprise Me" Button** -- Needs embeddings first
3. **Listening History Timeline** -- Nice-to-have visualization, not core engine work
4. **Full "Reading Life" Analytics Dashboard** -- Build after the engine is solid; analytics are a reward, not a prerequisite

---

## Architecture Implications (Single-User Fork)

Since this is a fork for one person, several AudiPy design choices can be simplified or redirected:

| AudiPy Design | Audiblimey Direction |
|---------------|---------------------|
| MySQL/MariaDB with 27 tables | Keep MySQL for relational data. Add vector storage for embeddings (ChromaDB sidecar, LanceDB file-based, or MySQL 9.0 vector type if available). |
| Multi-user OAuth with JWT | Strip to single-user. Audible OAuth stays for API access. Remove JWT session management, user_oauth_tokens complexity. |
| React 19 + MUI frontend | Keep or rewrite in SvelteKit (your preferred stack). The frontend is presentation -- the engine is backend. |
| FastAPI backend | Keep. Python is the right language for the recommendation engine, embedding pipeline, and LLM integration. |
| Celery + Redis task queue | Evaluate: single-user may not need a task queue. Background threads or simple subprocess calls (which AudiPy already uses) might suffice. |
| 142 fields per book | Keep the rich schema. Every field is potential signal for embeddings and filtering. |

**The stack question**: You prefer SvelteKit + TypeScript for frontend. AudiPy is React 19 + MUI. Two options:
1. Keep React (less work, fork stays close to upstream)
2. Rewrite frontend in SvelteKit (matches your stack, more work, diverges from upstream)

This is a "flag and ask" moment per your DevSoul preferences.

---

## The Compounding Flywheel (Refined)

```
Goodreads Ratings + Audible Library
         ↓
  Unified Book Identity (ISBN ↔ ASIN)
         ↓
  Rating-Weighted Author/Narrator/Series Scoring
         ↓
  Book Embeddings (descriptions + reviews + metadata)
         ↓
  User Taste Vector (rated-weighted centroid)
         ↓
  Taste Profile Document (LLM-generated, user-correctable)
         ↓
  Similarity Search + Natural Language Discovery
         ↓
  Explained Recommendations with Feedback Loop
         ↓
  Better Taste Vector (feedback refines the centroid)
         ↓
  (cycle repeats, engine gets sharper with every interaction)
```

Each layer feeds the next. Skip a layer and the one above it is weaker. Build them in order and each new feature inherits the quality of everything below it.

---

## Questions

### Answered (from Session 1)
- **Q**: Fork or clean-room? **A**: Fork AudiPy.
- **Q**: Goodreads history? **A**: Substantial rating history available.
- **Q**: Single-user or multi-user? **A**: Single-user.
- **Q**: LLM APIs or local models? **A**: LLM APIs (OpenAI or similar).

### New Questions
- **Q**: Frontend: keep React 19 (less work, closer to upstream) or rewrite in SvelteKit (matches your stack, diverges from fork)?
- **Q**: MySQL vector support: do you want to add pgvector via a PostgreSQL sidecar for embeddings, use ChromaDB/LanceDB as a file-based vector store, or try MySQL 9.0's native vector type?
- **Q**: Goodreads export: have you already exported your data as CSV? If so, how many rated books and what shelves do you use? This sizes the import work.
- **Q**: Audible catalog scope: should the engine recommend from the full Audible catalog (requires crawling/expanding the local catalog) or only from books discoverable through your existing authors/narrators/series (current AudiPy approach)?

## Next Steps
- [ ] Fork AudiPy to audiblimey repo
- [ ] Export Goodreads CSV, assess data volume and shelf taxonomy
- [ ] Build Goodreads CSV parser (extract: title, author, ISBN13, rating, shelves, review text, date_read)
- [ ] Research ISBN-to-ASIN mapping: test Open Library API match rate against 50 Goodreads books
- [ ] Prototype rating-weighted author scoring query against AudiPy's MySQL schema
- [ ] Decide: React 19 vs SvelteKit for frontend
- [ ] Decide: vector storage approach for embeddings
