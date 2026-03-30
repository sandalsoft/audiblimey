# audiblimey

Personal audiobook recommendation engine that fuses your Audible library with Goodreads ratings to surface taste-driven recommendations. Every recommendation explains *why* it was suggested.

Built for one person's 696+ book Audible library. Single-user, local-first.

## What It Does

- **Scored recommendations** — 4-component rating-weighted scoring (author affinity, narrator preference, series urgency, negative signals from abandoned shelves) with recency decay
- **Series urgency** — ranks incomplete series by progress × rating, shows next book with pricing
- **Library browser** — search and filter your Audible library by title, completion status
- **Book detail** — full metadata with clickable author/narrator links, pricing, listening progress
- **Author & narrator profiles** — stats grid (book count, avg rating, total time) and book list
- **Goodreads import** — CSV upload with ISBN-to-ASIN matching (direct ISBN, Open Library API, fuzzy title+author)
- **Audible library sync** — pulls books, authors, narrators, listening progress into PostgreSQL

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | SvelteKit 2.55, Svelte 5.55, Tailwind CSS 4.2, TypeScript |
| Backend | Python FastAPI 0.124, PostgreSQL 16 + pgvector |
| Data bridge | SvelteKit remote functions (`.remote.ts`) with Valibot validation |
| Design | Dark & warm HSL tokens, Lora headings, DM Sans body |
| External APIs | Audible (via `audible` Python library), Open Library (ISBN lookup) |

## Quickstart

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (for PostgreSQL + pgvector)
- [Node.js](https://nodejs.org/) 20+ and [pnpm](https://pnpm.io/)
- Python 3.11+

### 1. Start the database

```bash
docker compose up -d
```

This starts PostgreSQL 16 with pgvector on port 5432. The schema auto-migrates from `db/migrations/` on first run.

### 2. Set up Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows
pip install -r requirements.txt
```

> **Note:** Activate the venv in every new terminal session before running the backend or tests.

### 3. Start the FastAPI backend

```bash
uvicorn audiblimey.api.main:app --reload --port 8000
```

The API runs at [http://localhost:8000](http://localhost:8000). Health check: `GET /health`.

### 4. Install frontend dependencies

```bash
pnpm install
```

### 5. Start the SvelteKit dev server

```bash
pnpm dev
```

The app runs at [http://localhost:5173](http://localhost:5173). The Vite dev server proxies `/api/*` and `/health` to the FastAPI backend automatically.

### 6. Import your data

Open the app and navigate to the **Import** page from the sidebar:

1. **Goodreads CSV** — export your Goodreads library as CSV, then upload it on the Import page
2. **Audible sync** — requires Audible auth tokens pre-populated in the `user_audible_accounts` table (see [Audible Auth](#audible-auth) below)

## How to Use

### Dashboard (Home)

The main page shows two sections:

- **Recommendations** — paginated cards scored 0–100%, each with an explanation of why it was recommended. Click the dismiss button (×) to remove books you're not interested in.
- **Continue Your Series** — incomplete series ranked by urgency. Each card shows a progress bar, urgency badge (High/Medium/Low), and the next unowned book with pricing.

### Library

Browse your full Audible library. Use the search bar to find books by title, or filter by listening status (All, Finished, In Progress, Not Started). Click any book to open its detail page.

### Book Detail

Shows full metadata: title, subtitle, runtime, language, publisher, release date. Authors and narrators are clickable links to their profile pages. If the book belongs to a series, the series is listed with sequence numbers. A pricing card shows member price, list price, and credit price. If you've started listening, a progress bar shows your completion percentage.

### Author & Narrator Profiles

Accessed by clicking an author or narrator name on any book detail page. Shows a stats grid (books in your library, average rating, total listening time) and a grid of all their books that you own.

### Import

Three sections:

1. **Goodreads CSV Upload** — select your exported CSV file and click Upload. The system matches Goodreads books to Audible ASINs using a 3-strategy pipeline (direct ISBN, Open Library API, fuzzy title+author matching).
2. **Audible Sync** — click "Start Sync" to pull your Audible library. Shows sync status with progress. Prevents concurrent syncs (returns 409 if one is already running).
3. **Import Stats** — after importing, view match rate, rating distribution, top shelves, match source breakdown, and import history.

## API Endpoints

### Recommendations
- `GET /api/recommendations` — scored recommendations with explainability (limit, offset, min_score, suggestion_type)
- `GET /api/recommendations/series` — incomplete series ranked by urgency
- `POST /api/recommendations/{id}/dismiss` — dismiss a recommendation

### Library
- `GET /api/library` — paginated library (limit, offset, search, status)
- `GET /api/books/{asin}` — book detail with authors, narrators, series, pricing
- `GET /api/authors/{id}` — author profile with stats and book list
- `GET /api/narrators/{id}` — narrator profile with stats and book list

### Import & Sync
- `POST /api/import/goodreads` — upload Goodreads CSV (multipart/form-data)
- `GET /api/import/stats` — import statistics
- `GET /api/import/history` — import history
- `POST /api/sync/audible` — trigger Audible library sync
- `GET /api/sync/status` — sync job status

### Health
- `GET /health` — service health check

## Running Tests

```bash
# Python backend tests (88 tests)
python3 -m pytest tests/ -v

# SvelteKit type checking
pnpm check
```

## Audible Auth

Audible library sync requires authentication tokens stored in the `user_audible_accounts` table. The OAuth flow from [AudiPy](https://github.com/dbarkman/AudiPy) (`phase1_authenticate.py`) generates these tokens. No OAuth UI exists yet — tokens must be inserted directly into the database.

## Project Structure

```
audiblimey/
├── audiblimey/              # Python backend
│   ├── api/
│   │   ├── main.py          # FastAPI app
│   │   └── routes/          # API route modules
│   ├── engine/
│   │   ├── scoring.py       # 4-component recommendation scoring
│   │   └── explainability.py # Explanation text generator
│   ├── importers/
│   │   └── goodreads.py     # Goodreads CSV parser
│   ├── matching/
│   │   └── isbn_asin.py     # 3-strategy ISBN→ASIN matching
│   ├── sync/
│   │   └── audible.py       # Audible library sync (PostgreSQL)
│   └── db.py                # Database connection utilities
├── src/                     # SvelteKit frontend
│   ├── lib/
│   │   ├── api/             # Remote functions (.remote.ts)
│   │   └── components/      # Svelte 5 components
│   └── routes/              # File-based routing
│       ├── +page.svelte     # Dashboard (recommendations + series)
│       ├── library/         # Library browser
│       ├── books/[asin]/    # Book detail
│       ├── authors/[id]/    # Author profile
│       ├── narrators/[id]/  # Narrator profile
│       └── import/          # Import & sync UI
├── db/migrations/           # PostgreSQL schema (auto-runs on first docker compose up)
├── tests/                   # pytest tests
├── docker-compose.yml       # PostgreSQL 16 + pgvector
└── package.json             # Frontend dependencies
```

## Roadmap

- [x] **M001** — Goodreads import, ISBN matching, rating-weighted scoring engine, recommendation API
- [x] **M002** — SvelteKit frontend, Audible sync, library browser, book detail, author/narrator profiles
- [ ] **M003** — Vector embeddings (OpenAI text-embedding-3-small), taste profiles, natural language search

## Credits

Fork of [AudiPy](https://github.com/dbarkman/AudiPy) by David Barkman. Rewritten with PostgreSQL + pgvector, rating-weighted scoring, and a SvelteKit frontend.

## License

Private / personal use.
