"""
app.py
======
FastAPI application entry point for the X (Twitter) Scraper.

Responsibilities:
    - Configure structured logging (file + stdout).
    - Create and configure the FastAPI app instance.
    - Mount static files and Jinja2 templates.
    - Register all API routers from the ``routes`` package.
    - Wire startup/shutdown lifecycle hooks (provider init + teardown).
    - Serve the HTML dashboard on GET /.
    - Expose the Uvicorn run target when executed directly.

Windows / Python 3.14 Note:
    Python 3.14 changed the default Windows asyncio event loop from
    ProactorEventLoop to SelectorEventLoop. Playwright launches Chromium
    using asyncio.create_subprocess_exec, which ONLY works on
    ProactorEventLoop. We must set WindowsProactorEventLoopPolicy before
    any event loop is created. asyncio.run() (used internally by uvicorn)
    calls asyncio.new_event_loop() which is determined by the active
    policy — so changing the POLICY (not the loop) is the correct fix.
    The policy is deprecated in 3.14 and planned for removal in 3.16;
    we suppress those warnings since we have no alternative until uvicorn
    exposes loop_factory support.
"""

import sys
import warnings

# ---------------------------------------------------------------------------
# CRITICAL: Windows ProactorEventLoop fix — must run before any import that
# touches asyncio internals (uvicorn, fastapi, starlette all do on import).
# ---------------------------------------------------------------------------
# Why set_event_loop_policy and NOT set_event_loop:
#   asyncio.run() (called by uvicorn.run()) always creates a FRESH loop via
#   asyncio.new_event_loop(), which delegates to the active POLICY.
#   set_event_loop() only changes the "current" loop reference — asyncio.run()
#   ignores it and creates its own. Therefore only changing the POLICY works.
if sys.platform == "win32":
    import asyncio as _asyncio
    with warnings.catch_warnings():
        # WindowsProactorEventLoopPolicy is deprecated in Python 3.14 and
        # scheduled for removal in 3.16. Suppress warnings until uvicorn
        # gains native loop_factory support (tracked upstream).
        warnings.simplefilter("ignore", DeprecationWarning)
        _asyncio.set_event_loop_policy(_asyncio.WindowsProactorEventLoopPolicy())

import logging
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from routes.scrape import router as scrape_router
from routes.status import router as status_router
from routes.files import router as files_router
from routes.ai import router as ai_router

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------

config.LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format=config.LOG_FORMAT,
    handlers=[
        logging.FileHandler(config.APP_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("twitter_scraper.app")

if sys.platform == "win32":
    logger.info(
        "Windows detected: ProactorEventLoop policy applied "
        "(required for Playwright subprocess support on Python 3.12–3.15)."
    )

# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager — replaces the deprecated on_event hooks.

    Startup:  initialise directories and data provider.
    Shutdown: release the Playwright browser gracefully.
    """
    from dependencies import provider

    # ── Startup ───────────────────────────────────────────────────────────
    logger.info("=== X Scraper Dashboard starting up (v2.0.0) ===")

    for directory in [
        config.SCRAPED_DATA_DIR,
        config.SESSIONS_DIR,
        config.STATE_DIR,
        config.LOGS_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    try:
        await provider.initialise()
        logger.info("Data provider initialised successfully.")
    except Exception as exc:
        logger.warning(
            "Provider initialisation warning: %s — "
            "Expected if auth.json has not been generated yet.",
            exc,
        )

    logger.info("Server ready. Dashboard: http://%s:%d", config.SERVER_HOST, config.SERVER_PORT)

    yield  # Server is now running; control passes to request handlers.

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("Server shutting down — releasing provider resources.")
    try:
        await provider.shutdown()
    except Exception as exc:
        logger.error("Error during provider shutdown: %s", exc)
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="X (Twitter) Scraper Dashboard",
    description=(
        "A modular FastAPI + Playwright web application that retrieves posts "
        "from public X (Twitter) profiles in sequential batches of 10, "
        "persisting results as JSON files with full pagination state tracking."
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Static Files & Templates
# ---------------------------------------------------------------------------

app.mount(
    "/static",
    StaticFiles(directory=str(config.STATIC_DIR)),
    name="static",
)
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# API Routers
# ---------------------------------------------------------------------------


app.include_router(status_router, tags=["Status"])
app.include_router(scrape_router, tags=["Scraping"])
app.include_router(files_router, tags=["Files"])
app.include_router(ai_router, tags=["AI"])

# ---------------------------------------------------------------------------
# Dashboard (HTML)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard(request: Request) -> HTMLResponse:
    """Serve the main interactive dashboard HTML page."""
    return templates.TemplateResponse(request=request, name="index.html")

# ---------------------------------------------------------------------------
# Development Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=config.SERVER_RELOAD,
        log_level="info",
    )
