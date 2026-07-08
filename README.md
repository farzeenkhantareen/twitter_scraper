# X (Twitter) Scraper — Production Web Application

A complete, modular, production-quality web application for retrieving posts from public X (Twitter) profiles in sequential batches of 10, with persistent state tracking, JSON file storage, and a premium dark-mode dashboard.

---

## Table of Contents

1. [Project Architecture](#project-architecture)
2. [Installation](#installation)
3. [Virtual Environment Setup](#virtual-environment-setup)
4. [Dependency Installation](#dependency-installation)
5. [Configuration](#configuration)
6. [Generating Session Authentication](#generating-session-authentication)
7. [Running the Server](#running-the-server)
8. [Using the Dashboard](#using-the-dashboard)
9. [API Documentation](#api-documentation)
10. [JSON Output Format](#json-output-format)
11. [Troubleshooting](#troubleshooting)
12. [Future Improvements](#future-improvements)

---

## Project Architecture

```
twitter_scraper/
│
├── app.py                  # FastAPI entry point — wires all modules together
├── config.py               # Central configuration (paths, timeouts, browser args)
├── dependencies.py         # Shared singleton instances (provider, state, file mgr)
├── models.py               # Pydantic models — Post, ScraperState, API responses
├── state_manager.py        # Reads/writes state/state.json (session cursor)
├── file_manager.py         # Serialises batches to JSON; handles batch file lookups
├── session.py              # Legacy compatibility stub (deprecated)
│
├── provider/               # ── Data Provider Layer ──────────────────────────────
│   ├── __init__.py         # Package init — re-exports public API
│   ├── base.py             # Abstract DataProvider + exception hierarchy
│   └── playwright_provider.py  # Playwright/Chromium implementation
│
├── routes/                 # ── API Route Handlers ───────────────────────────────
│   ├── __init__.py         # Package init
│   ├── scrape.py           # POST /scrape/start, POST /scrape/next
│   ├── status.py           # GET /status
│   └── files.py            # POST /reset, GET /download/latest
│
├── templates/
│   └── index.html          # Jinja2 dashboard template (two-panel layout)
│
├── static/
│   ├── style.css           # Premium dark glassmorphism CSS
│   └── script.js           # Vanilla JS frontend controller
│
├── scraped_data/           # Auto-created — batch JSON output files
│   └── username_batch_001.json
│
├── sessions/               # Auto-created — Playwright auth state
│   └── auth.json           # ← YOU MUST GENERATE THIS (see below)
│
├── state/                  # Auto-created — session cursor
│   └── state.json
│
├── logs/                   # Auto-created — log files
│   ├── app.log             # General application events
│   └── scraper.log         # Structured batch execution metrics
│
├── import_cookies.py       # Utility: converts browser-exported cookies to auth.json
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

### Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Provider isolation** | All platform-specific code lives in `provider/playwright_provider.py`. Routes import only `DataProvider` (abstract). |
| **Single config source** | `config.py` defines every constant. No hardcoded values in modules. |
| **No circular imports** | Shared singletons live in `dependencies.py`, imported by routes. |
| **Normalised output** | `Post` model maps all required fields. Providers must return `Post` objects. |
| **State persistence** | `state/state.json` survives server restarts; the session cursor is never lost. |

---

## Installation

### Prerequisites

- Python **3.12** or later
- Windows, macOS, or Linux
- Git (optional, for cloning)

### Clone or Download

```bash
git clone <repository-url>
cd twitter_scraper
```

---

## Virtual Environment Setup

Always use an isolated virtual environment to avoid dependency conflicts.

```bash
# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# Windows (Command Prompt)
python -m venv venv
venv\Scripts\activate.bat

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` in your terminal prompt when the environment is active.

---

## Dependency Installation

With the virtual environment **active**:

```bash
pip install -r requirements.txt
```

Then install the Playwright Chromium browser binary:

```bash
playwright install chromium
```

> [!NOTE]
> `playwright install chromium` downloads ~150 MB. It only needs to be run once per machine.

---

## Configuration

All application settings are centralised in [`config.py`](config.py).

### Key Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `BATCH_SIZE` | `10` | Posts per retrieval batch |
| `SERVER_HOST` | `127.0.0.1` | Uvicorn bind address |
| `SERVER_PORT` | `8000` | Uvicorn listen port |
| `SERVER_RELOAD` | `True` | Hot-reload for development |
| `BROWSER_HEADLESS` | `True` | Run Chromium without a visible window |
| `MAX_SEARCH_SCROLLS` | `35` | Max scroll attempts to find the boundary post |
| `MAX_COLLECTION_SCROLLS` | `50` | Max scroll attempts when collecting a batch |
| `PAGE_LOAD_TIMEOUT_MS` | `30000` | Navigation timeout in milliseconds |
| `MAX_RETRIES` | `3` | Retry attempts for transient network errors |

To change any setting, edit `config.py` directly. No `.env` file is required.

---

## AI Analyst Mode (Groq API Key Setup)

The dashboard includes an **AI Analyst Mode** that enables chatting with your scraped datasets. To use this feature, you must configure your Groq API key:

### Method A — Using a `.env` File (Recommended)
1. Create a file named `.env` in the root of the project. (Note: `.env` is ignored by Git, ensuring your key is never committed to GitHub).
2. Add your Groq API key to this file:
   ```env
   GROQ_API_KEY=your_actual_groq_api_key
   ```

### Method B — Setting the Environment Variable directly
Alternatively, you can set the key in your terminal session before running the application:

* **Windows (PowerShell)**:
  ```powershell
  $env:GROQ_API_KEY="your_actual_groq_api_key"
  ```
* **Windows (Command Prompt)**:
  ```cmd
  set GROQ_API_KEY=your_actual_groq_api_key
  ```
* **macOS / Linux**:
  ```bash
  export GROQ_API_KEY="your_actual_groq_api_key"
  ```

---

## Generating Session Authentication

The scraper authenticates by loading a pre-saved Playwright browser state that contains your X (Twitter) session cookies.

> [!IMPORTANT]
> **Privacy & Security Guarantee:**
> * **Strictly Local**: Your X (Twitter) login session is kept entirely local on your machine.
> * **Completely Ignored by Git**: The folders `sessions/` and the file `cookies.json` are registered in the project's [`.gitignore`](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/.gitignore).
> * **Safe from GitHub**: Git is blocked from tracking or pushing these credentials. They will never be uploaded to GitHub or any remote repository.

### Method 1 — Playwright Codegen (Recommended)

```bash
playwright codegen --save-storage=sessions/auth.json x.com
```

1. A Chromium browser window opens.
2. Log in to X (Twitter) with your account.
3. Browse to the X homepage (or any profile).
4. **Close the browser window**.
5. `sessions/auth.json` is now saved with your session cookies.

### Method 2 — Import Browser Cookies

If you have already exported cookies from your browser using a cookie-export extension (e.g. Cookie-Editor):

```bash
python import_cookies.py cookies.json sessions/auth.json
```

This converts the standard browser cookie format into the Playwright storage-state format.

---

## Running the Server

### Development (recommended)

```bash
python app.py
```

Or equivalently:

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

### Production (no auto-reload)

Edit `config.py` and set `SERVER_RELOAD = False`, then:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

> [!IMPORTANT]
> Use `--workers 1`. The application uses an asyncio lock for concurrency control and a module-level Playwright browser instance. Multiple workers will not share these correctly.

Open your browser at: **http://127.0.0.1:8000**

### Interactive API Docs

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

---

## Using the Dashboard

The dashboard is a two-panel layout:

**Left panel (controls):**
1. Enter the target X username (without `@`).
2. Click **Retrieve First 10 Posts** — starts a new session, collects the first 10 posts, saves `username_batch_001.json`.
3. Click **Retrieve Next 10 Posts** — continues from where you left off, saves `username_batch_002.json`, etc.
4. Click **Download JSON** — downloads the most recently saved batch file.
5. Click **Reset** — clears the session cursor (saved JSON files are kept).

**Right panel (dashboard):**
- Real-time metrics: target account, current batch, total posts collected, latest filename.
- Live status badge with animated indicator.
- Progress bar and step messages during active scraping.
- Activity log feed with timestamped events.

---

## API Documentation

### `GET /`
Serves the HTML dashboard.

---

### `GET /status`
Returns the current scraper state and live progress.

**Response:**
```json
{
  "username": "elonmusk",
  "batch": 3,
  "total_scraped": 30,
  "last_file": "elonmusk_batch_003.json",
  "status": "Completed Successfully",
  "progress_message": "",
  "error_message": null
}
```

---

### `POST /scrape/start`
Resets any previous session and retrieves the first batch (posts 1–10).

**Request:**
```json
{ "username": "elonmusk" }
```

**Response (200):**
```json
{
  "message": "First batch retrieved successfully.",
  "batch": 1,
  "count": 10,
  "filename": "elonmusk_batch_001.json"
}
```

**Errors:**
| Code | Cause |
|------|-------|
| 400 | Invalid/empty username, account not found, account suspended, account protected, rate limited |
| 401 | sessions/auth.json missing or session expired |
| 409 | Another scrape already in progress |
| 500 | Unexpected provider or server error |

---

### `POST /scrape/next`
Retrieves the next batch, continuing from the last saved post ID.

**Response (200):**
```json
{
  "message": "Batch 2 retrieved successfully.",
  "batch": 2,
  "count": 10,
  "filename": "elonmusk_batch_002.json"
}
```

Returns `count: 0` when the timeline is exhausted.

**Errors:** Same as `/scrape/start` plus `400` if no active session exists.

---

### `POST /reset`
Clears the session cursor. Batch JSON files are preserved.

**Response (200):**
```json
{ "message": "Scraping progress has been reset successfully." }
```

---

### `GET /download/latest`
Streams the most recently written JSON batch file as a download attachment.

**Response:** Binary file stream (`application/json`).

**Errors:**
| Code | Cause |
|------|-------|
| 404 | No batch files exist |

---

## JSON Output Format

Each batch is saved as `scraped_data/<username>_batch_<NNN>.json`.

**Example record:**
```json
{
  "post_id": "1802345678901234567",
  "username": "elonmusk",
  "display_name": "Elon Musk",
  "created_at": "2024-06-18T14:22:00.000Z",
  "text": "The thing I find most surprising about AI is how fast it's moving #AI #Tech",
  "url": "https://x.com/elonmusk/status/1802345678901234567",
  "reply_count": 1420,
  "repost_count": 3841,
  "like_count": 28500,
  "view_count": 14200000,
  "hashtags": ["AI", "Tech"],
  "mentions": [],
  "media_urls": ["https://pbs.twimg.com/media/example.jpg"],
  "external_links": []
}
```

---

## Troubleshooting

### "Authentication Required" Error
**Cause:** `sessions/auth.json` is missing or the session has expired.  
**Fix:** Re-run the Playwright codegen command:
```bash
playwright codegen --save-storage=sessions/auth.json x.com
```
Log in to X, then close the browser window.

---

### "Username does not exist on X"
**Cause:** The handle was mistyped, or the account was deleted.  
**Fix:** Verify the username at `https://x.com/<username>`.

---

### "Account is protected"
**Cause:** The profile is private — only approved followers can see posts.  
**Fix:** The scraper only supports public profiles. Try a different account.

---

### "Rate limit exceeded"
**Cause:** X is temporarily blocking requests from your session.  
**Fix:** Wait 10–15 minutes before retrying. Avoid running multiple batches in rapid succession.

---

### Tweets failed to load / Crash screenshot saved
**Cause:** X changed its HTML structure, or a CAPTCHA appeared.  
**Fix:**
1. Check `logs/app.log` for detailed error context.
2. Open the crash screenshot saved in `logs/` (e.g. `crash_elonmusk_2_1234567890.png`).
3. If a CAPTCHA appeared, log in interactively and regenerate `sessions/auth.json`.
4. If X changed its DOM structure, the selectors in `provider/playwright_provider.py` may need updating.

---

### Server port already in use
**Cause:** Another process is running on port 8000.  
**Fix:** Change `SERVER_PORT` in `config.py`, or stop the conflicting process:
```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

---

### "No active scraping session. Use POST /scrape/start first."
**Cause:** You clicked "Retrieve Next 10 Posts" before starting a session (or after a reset).  
**Fix:** Click "Retrieve First 10 Posts" first.

---

## Future Improvements

| Feature | Notes |
|---------|-------|
| **Official X API v2 provider** | Add `provider/api_provider.py` implementing `DataProvider` using the official API — no changes to routes or UI needed. |
| **Multi-user / concurrent sessions** | Replace the asyncio lock with a queue-based worker pool; replace module singletons with a Redis-backed session store. |
| **Proxy rotation** | Add proxy configuration to `config.py` and pass it to `_BrowserSession`. |
| **Scheduled batch retrieval** | Integrate APScheduler or Celery to auto-fetch new batches on a cron schedule. |
| **WebSocket progress streaming** | Replace HTTP polling with a WebSocket endpoint for zero-latency progress updates. |
| **Database storage** | Add an optional SQLite or PostgreSQL backend to `file_manager.py` for queryable post storage. |
| **Export formats** | Add CSV and NDJSON export options alongside the existing JSON download. |
| **Docker container** | Add a `Dockerfile` and `docker-compose.yml` for one-command deployment. |
| **Authentication UI** | Build an in-browser flow to import cookies without needing terminal access. |
| **Post deduplication across sessions** | Maintain a global seen-IDs store to prevent re-saving posts already collected in earlier sessions. |
