# 10x Analysis: Audiblimey (Audible/Goodreads Recommendation Engine)
Session 1 | Date: 2026-03-29

## Current Value

AudiPy (the upstream reference project by dbarkman) is a well-built Audible Library Analyzer that:
- Imports a user's full Audible library via OAuth
- Generates 4 recommendation types: series continuation, author discovery, narrator discovery, and similar books
- Applies smart purchase logic ($12.66 cash-vs-credit threshold)
- Stores 142+ metadata fields per book across a 23-table MySQL schema
- Provides a React + FastAPI web interface for browsing library and recommendations

**Who it serves**: Audible power users (696+ books) who want to find their next listen without endless browsing.

**Core limitation**: Recommendations are catalog-driven (what exists by same author/narrator/series), not taste-driven. There's no understanding of *why* a user loved a book — genre affinity, narrative style, thematic preferences, pacing, mood. It answers "what else did this author write?" but not "what else would I love?"

## The Question

**What would make this 10x more valuable as a recommendation engine — something that makes Audible's own recommendations feel broken by comparison?**

The user's stated goal: build a recommendation engine based on Audible + Goodreads history. That's the north star.

---

## Massive Opportunities

### 1. Goodreads Taste Graph Integration
**What**: Import the user's Goodreads ratings, shelves, and reviews to build a true taste profile. Goodreads has what Audible lacks — explicit preference signals. A 5-star rating on Goodreads is a stronger signal than "you own this book." Cross-reference Goodreads ISBNs with Audible ASINs to merge the two datasets into a unified reading identity.
**Why 10x**: Audible knows what you bought. Goodreads knows what you loved. Neither alone tells the full story. The combination creates a preference model that neither platform offers. A user who rated 200 books on Goodreads and owns 700 on Audible has an incredibly rich signal set that no existing service leverages together.
**Unlocks**: Taste-based recommendations instead of catalog-based ones. "You gave 5 stars to three unreliable narrator thrillers — here are the best-rated ones you haven't read, available on Audible for under $13."
**Effort**: High — Goodreads API is deprecated, so you'd need scraping (RSS feeds still work for shelves), CSV export parsing, or the user's Goodreads data export. ISBN-to-ASIN matching requires a mapping layer.
**Risk**: Goodreads API deprecation means this is fragile. Amazon could further lock down. Mitigation: support CSV import as primary path (Goodreads lets users export), treat API/scraping as bonus.
**Score**: 🔥

### 2. Embedding-Based "Taste Fingerprint" Engine
**What**: Generate vector embeddings for every book using descriptions, reviews, and metadata (genre, length, narrator style, publication era). Build a user taste vector from their rated/owned books. Recommend by nearest-neighbor search in embedding space. Use an LLM to generate the embeddings or a fine-tuned sentence transformer.
**Why 10x**: This is the difference between "more books by Brandon Sanderson" and "books with the same epic scope, intricate magic systems, and satisfying payoffs — even by authors you've never heard of." It surfaces hidden gems. It's the recommendation leap that Spotify made with Discover Weekly.
**Unlocks**: Cross-genre discovery, "if you liked X you'll love Y" that actually works, mood-based browsing, and a recommendation quality that improves with every book the user rates.
**Effort**: Very High — needs embedding pipeline, vector DB (pgvector works with existing PostgreSQL preference), similarity search, and careful prompt engineering or model selection.
**Risk**: Cold start for new users. Embedding quality depends on description quality. Mitigation: fall back to AudiPy's existing catalog-based recs for new users, graduate to embeddings as data accumulates.
**Score**: 🔥

### 3. Social Taste Matching ("Readers Like You")
**What**: Let users opt in to share their anonymized taste profiles. Match users with similar taste fingerprints. Surface books that your taste-twins loved but you haven't discovered yet. Think "collaborative filtering" but for a community of audiobook nerds, not Amazon's entire customer base.
**Why 10x**: Amazon's collaborative filtering is diluted across millions of casual buyers. A focused community of audiobook enthusiasts produces dramatically better signal. The person who shares your taste in 50 books is a better recommendation source than an algorithm trained on everyone.
**Unlocks**: Community features, trust networks ("I always agree with this person's ratings"), book clubs, and a network effect that makes the product harder to leave the more people join.
**Effort**: Very High — needs user accounts, privacy controls, matching algorithm, and enough users to be useful.
**Risk**: Chicken-and-egg: needs critical mass to be valuable. Mitigation: start with a "taste twin" feature that compares two users who share links, before building full community.
**Score**: 👍

### 4. "Reading Life" Analytics Dashboard
**What**: A rich, visual, personal analytics experience. Total hours listened, genres over time, narrator loyalty score, reading velocity trends, spending analysis, series completion rates, longest streak, most re-listened book. Think Spotify Wrapped but for your entire audiobook history, available year-round.
**Why 10x**: People are fascinated by data about themselves. This turns the library from a list into a mirror. It drives engagement (users come back to check stats), creates shareability (annual wrap-ups), and surfaces patterns the user didn't know about themselves ("you listen to 73% more sci-fi in winter").
**Unlocks**: Shareable year-in-review cards, goal setting ("listen to 50 books this year"), genre diversification nudges, and deep engagement with the platform even when users aren't looking for a new book.
**Effort**: High — needs data aggregation, visualization layer (D3.js fits the user's stack), time-series analysis.
**Risk**: Low technical risk, mostly design challenge. Risk is building vanity metrics nobody cares about. Mitigation: start with the 5 stats users manually track in spreadsheets today.
**Score**: 🔥

---

## Medium Opportunities

### 1. Natural Language Book Search ("Find me something like...")
**What**: A search bar where users type "a cozy mystery with a female detective, under 10 hours, narrated by someone with a British accent" and get results from Audible's catalog matched against their taste profile. Powered by LLM + embeddings.
**Why 10x**: Current discovery is browse-based (categories, bestseller lists). This lets users articulate exactly what they're in the mood for. It's the difference between browsing Netflix and telling a knowledgeable friend what you want.
**Impact**: Converts "I don't know what to listen to next" from a 30-minute browsing session to a 30-second conversation.
**Effort**: Medium — needs embedding search + LLM query interpretation. Can start with metadata filtering and graduate to semantic search.
**Score**: 🔥

### 2. TBR (To-Be-Read) Queue with Smart Ordering
**What**: A managed "next up" queue that considers: series order (don't suggest book 3 before book 2), mood rotation (don't stack 5 heavy thrillers), length variation (alternate long and short), credit/sale optimization (suggest the one that just went on sale first), and narrator variety.
**Why 10x**: The hardest decision for a heavy listener isn't "what should I read?" — it's "what should I read *next*?" This turns a pile of recommendations into a curated listening plan.
**Impact**: Reduces decision fatigue, increases listen-through rate, surfaces books that would otherwise sit unplayed.
**Effort**: Medium — needs queue data model, ordering algorithm, user controls for preferences.
**Score**: 👍

### 3. Price Intelligence & Deal Alerts
**What**: Track historical prices for recommended books. Alert users when a book on their wishlist drops in price, goes on daily deal, or becomes included in Plus catalog. Show price trends. Recommend "buy now" vs "wait for a sale" based on price history.
**Why 10x**: Audible's pricing is opaque and volatile. Daily deals, sales, and Plus additions happen without notice. Being the service that tells you "that book you want is $5 today, it's normally $25" creates a save-money-on-books habit loop.
**Impact**: Direct financial value to users. Creates daily engagement (check for deals). Turns recommendations into actionable, time-sensitive opportunities.
**Effort**: Medium — needs price scraping/tracking, alert system, historical price DB.
**Score**: 👍

### 4. Multi-Source Library Unification
**What**: Import not just Audible, but also Libro.fm, Chirp, local library apps (Libby/OverDrive), Apple Books, and Google Play Books. Build a single unified audiobook library across all platforms. Recommendations consider what you've already listened to everywhere, not just Audible.
**Why 10x**: Power listeners use multiple platforms. Getting a recommendation for a book you already own on Libby is frustrating. A unified view is something no platform offers because each wants to be your only platform.
**Impact**: Becomes the single source of truth for "my audiobook life." Lock-in through comprehensiveness.
**Effort**: Medium-High — each integration is independent work. Start with CSV/manual import, add APIs as available.
**Score**: 👍

### 5. Narrator Quality Scoring
**What**: Build a narrator rating system separate from book ratings. Track which narrators consistently appear in the user's highest-rated books. Surface narrator affinity as a first-class recommendation signal. Show "narrator match score" on recommended books.
**Why 10x**: Narrators make or break audiobooks in a way that has no parallel in print. A bad narrator can ruin a great book. A great narrator can elevate a mediocre one. No platform treats narrator preference as a primary discovery axis.
**Impact**: Prevents bad narrator experiences (saves 10+ hours per avoided bad listen). Creates a discovery path unique to audiobooks.
**Effort**: Medium — needs narrator metadata enrichment, rating correlation analysis, UI for narrator profiles.
**Score**: 🔥

---

## Small Gems

### 1. "Why This Recommendation" Explainability
**What**: Every recommendation shows a one-line reason: "Because you loved the first 3 books in this series" or "Your top-rated narrator performs this one" or "Readers with your taste rate this 4.6 stars."
**Why powerful**: Unexplained recommendations feel algorithmic and cold. Explained recommendations feel like advice from a friend. Dramatically increases click-through and trust.
**Effort**: Low — the recommendation engine already tracks source/type. Format it as human-readable text.
**Score**: 🔥

### 2. One-Click "Not Interested" with Learning
**What**: A dismiss button that feeds back into the recommendation model. Track *why* (wrong genre, already read in print, don't like this author). Over time, recommendations get sharper.
**Why powerful**: Negative signals are as valuable as positive ones. Every dismissal makes the engine smarter. Users feel heard.
**Effort**: Low — needs a feedback table and simple filtering logic.
**Score**: 🔥

### 3. "Continue Series" Prominent Nudge
**What**: On the dashboard, a persistent card showing "You're 3 books into a 7-book series. Book 4 is $8.99 (cash deal)." One tap to add to cart.
**Why powerful**: Series continuation is the highest-intent recommendation. Making it zero-friction converts browsers to buyers. AudiPy already has this data — just needs better surfacing.
**Effort**: Low — data exists in the schema, just needs a prominent UI component.
**Score**: 🔥

### 4. Reading Pace Estimator
**What**: Based on the user's average listening speed and daily listening time, show "At your pace, this 14-hour book will take ~6 days." On the queue view, show estimated completion dates for the whole queue.
**Why powerful**: Answers the question "do I have time for this before my road trip?" without mental math. Tiny feature, constant utility.
**Effort**: Low — needs listening history analysis for pace calculation, simple math for estimates.
**Score**: 👍

### 5. "Finish Rate" Indicator
**What**: Show what percentage of listeners finished each book (from Audible data if available, or from community data). A book with 90% finish rate is a different recommendation than one with 30%.
**Why powerful**: Star ratings don't capture "I gave up at chapter 4." Finish rate is a proxy for "is this actually engaging?" and it's a signal that audiobook listeners uniquely care about (10+ hour commitment).
**Effort**: Low-Medium — depends on data availability. Could start with community-reported data.
**Score**: 👍

---

## Recommended Priority

### Do Now (Quick wins, ship this week)
1. **"Why This Recommendation" Explainability** — Already have the data, just format it. Instant trust boost.
2. **"Continue Series" Prominent Nudge** — Highest-conversion recommendation, just needs better placement.
3. **One-Click "Not Interested" with Learning** — Starts the feedback loop immediately. Every dismissal is training data.

### Do Next (High leverage, next 2-4 weeks)
1. **Goodreads Import (CSV)** — The single biggest unlock for taste-based recommendations. CSV export is user-controlled, no API dependency. This is the foundation for everything else.
2. **Natural Language Book Search** — Transforms discovery from browsing to conversation. Can start simple with metadata filters before graduating to embeddings.
3. **Narrator Quality Scoring** — Unique to audiobooks, no competitor does this well. Built from data you already collect.

### Explore (Strategic bets, validate first)
1. **Embedding-Based Taste Fingerprint** — The long-term engine. Start with a prototype using OpenAI embeddings + pgvector. Validate that embedding similarity correlates with user preferences before going deep. Risk: embedding quality. Upside: recommendation quality that makes Audible's look primitive.
2. **"Reading Life" Analytics Dashboard** — High engagement potential. Validate by asking: would users share their stats? If yes, it's a growth engine. If no, it's a vanity feature.
3. **Social Taste Matching** — Needs critical mass. Start with a "compare with a friend" link-sharing feature to test whether taste-twin matching produces good recommendations before building community infrastructure.

### Backlog (Good but not now)
1. **Multi-Source Library Unification** — Valuable but each integration is independent work. Build the core engine on Audible + Goodreads first, expand platforms later.
2. **Price Intelligence & Deal Alerts** — Real value, but it's a different product (deal finder vs. recommendation engine). Build after core recommendations are solid.
3. **TBR Smart Queue** — Needs the recommendation engine to be strong first. Queue ordering is a polish feature on top of good recommendations.

---

## The Compounding Insight

The highest-leverage architecture decision is this: **Goodreads ratings + Audible ownership + dismissal feedback = a taste model that gets better with every interaction.** Every other feature builds on that foundation.

The priority order matters because each layer feeds the next:
- Goodreads import gives you explicit taste signals (ratings)
- Narrator scoring gives you audiobook-specific preference signals
- Embeddings let you generalize those signals to unseen books
- Explainability builds trust so users engage more
- Feedback loops sharpen everything over time

Skip straight to embeddings without the taste data, and you're building a fancy engine with no fuel. Get the data flowing first.

---

## Questions

### Answered
- **Q**: What does AudiPy already do? **A**: Full Audible OAuth, library import (696+ books), 4 recommendation types (series/author/narrator/similar), smart cash-vs-credit pricing, React + FastAPI web app with 23-table MySQL schema.
- **Q**: What's the gap? **A**: Recommendations are catalog-driven (same author/narrator/series), not taste-driven. No Goodreads integration. No user feedback loop. No embeddings or similarity beyond metadata matching.

### Blockers (need your input)
- **Q**: Do you plan to fork/extend AudiPy directly, or is audiblimey a clean-room build inspired by it? This affects whether we build on their MySQL schema or start fresh with PostgreSQL (your default).
- **Q**: Do you have a Goodreads account with substantial rating history? The Goodreads import feature's value depends on how much data is there.
- **Q**: Are you building this for yourself first (single-user tool) or targeting other audiobook enthusiasts from the start? This changes whether social features matter early.
- **Q**: What's your stance on using LLM APIs (OpenAI/Anthropic) for embedding generation vs. running local models? Cost vs. quality tradeoff.

## Next Steps
- [ ] Decide: fork AudiPy or clean build? (drives tech stack decisions)
- [ ] Validate: export your Goodreads data (CSV), assess data quality and volume
- [ ] Prototype: Goodreads CSV parser that extracts ratings, shelves, ISBNs
- [ ] Research: ISBN-to-ASIN mapping approaches (Open Library API, Amazon Product API, community databases)
- [ ] Prototype: pgvector setup with book description embeddings for 50 books, test similarity quality
