"""
config.py
=========
Central configuration module for the X (Twitter) Scraper application.

All environment-dependent settings, path constants, tunable parameters,
and feature flags are defined here. No other module should hardcode these
values — import from this module instead.
"""

from pathlib import Path
import os

# ---------------------------------------------------------------------------
# Load environment variables from .env if present
# ---------------------------------------------------------------------------
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip().strip('"').strip("'"))

# ---------------------------------------------------------------------------
# Directory Layout
# ---------------------------------------------------------------------------

#: Absolute path to the project root (directory containing this file).
BASE_DIR: Path = Path(__file__).resolve().parent

#: Directory where scraped JSON batches are stored.
SCRAPED_DATA_DIR: Path = BASE_DIR / "scraped_data"

#: Directory where the Playwright session auth.json lives.
SESSIONS_DIR: Path = BASE_DIR / "sessions"

#: Directory where the state.json progress file lives.
STATE_DIR: Path = BASE_DIR / "state"

#: Directory where all log files are written.
LOGS_DIR: Path = BASE_DIR / "logs"

#: Path to the Jinja2 HTML template directory.
TEMPLATES_DIR: Path = BASE_DIR / "templates"

#: Path to the static assets directory (CSS, JS).
STATIC_DIR: Path = BASE_DIR / "static"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

#: Path to the Playwright browser storage-state file (cookies + localStorage).
AUTH_SESSION_PATH: Path = SESSIONS_DIR / "auth.json"

# ---------------------------------------------------------------------------
# Scraping Parameters
# ---------------------------------------------------------------------------

#: Number of posts to collect per batch.
BATCH_SIZE: int = 10

#: Maximum number of DOM scroll operations when searching for the last post boundary.
MAX_SEARCH_SCROLLS: int = 35

#: Maximum number of DOM scroll operations when collecting a new batch.
MAX_COLLECTION_SCROLLS: int = 50

#: Base delay (seconds) between scroll operations to simulate human behaviour.
SCROLL_DELAY_SECONDS: float = 2.0

#: Additional jitter factor added to scroll delay (delay × jitter per attempt mod 3).
SCROLL_JITTER_FACTOR: float = 0.5

#: Timeout (ms) when waiting for the profile page to load (domcontentloaded).
PAGE_LOAD_TIMEOUT_MS: int = 30_000

#: Timeout (ms) when waiting for the first tweet article to appear in the DOM.
TWEET_SELECTOR_TIMEOUT_MS: int = 15_000

#: Short settle delay (ms) after page load before running error checks.
PAGE_SETTLE_DELAY_MS: int = 1_000

#: Maximum number of retry attempts for transient network or provider errors.
MAX_RETRIES: int = 3

#: Delay (seconds) between retry attempts (exponential backoff base).
RETRY_BASE_DELAY_SECONDS: float = 5.0

# ---------------------------------------------------------------------------
# Server Configuration
# ---------------------------------------------------------------------------

#: Host address for the Uvicorn server.
SERVER_HOST: str = "127.0.0.1"

#: Port for the Uvicorn server.
SERVER_PORT: int = 8000

#: Enable auto-reload (development mode). Set to False in production.
SERVER_RELOAD: bool = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

#: Log format string shared across all handlers.
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

#: Path to the general application log file.
APP_LOG_PATH: Path = LOGS_DIR / "app.log"

#: Path to the structured scraping execution metrics log.
SCRAPER_LOG_PATH: Path = LOGS_DIR / "scraper.log"

# ---------------------------------------------------------------------------
# Browser Configuration
# ---------------------------------------------------------------------------

#: Run Playwright's Chromium browser in headless mode.
BROWSER_HEADLESS: bool = True

#: User-agent string sent with every browser request.
BROWSER_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

#: Viewport width in pixels.
BROWSER_VIEWPORT_WIDTH: int = 1280

#: Viewport height in pixels.
BROWSER_VIEWPORT_HEIGHT: int = 800

#: Chromium launch arguments that reduce automation fingerprinting.
BROWSER_LAUNCH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
]

# ---------------------------------------------------------------------------
# Output Filename Pattern
# ---------------------------------------------------------------------------

#: Format string for batch output filenames.
#: Parameters: username (str), batch_number (int zero-padded to 3 digits).
BATCH_FILENAME_PATTERN: str = "{username}_batch_{batch_number:03d}.json"


