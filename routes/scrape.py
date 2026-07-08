"""
routes/scrape.py
================
POST /scrape/start  — Begin a new scraping session (batch 1).
POST /scrape/next   — Continue with the next batch for the active session.

Both endpoints:
  - Acquire the global concurrency lock (one scrape at a time).
  - Delegate to the configured DataProvider.
  - Persist state via StateManager.
  - Write output files via FileManager.
  - Write execution metrics to the structured scraper log.
  - Update the in-memory live_progress dict for real-time UI polling.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

import config
from models import ScrapeStartRequest, ScrapeResponse, ScraperState, SpecialScrapeResponse
from provider.base import (
    AccountProtectedError,
    AccountSuspendedError,
    AuthenticationError,
    ProviderError,
    RateLimitExceededError,
    UserNotFoundError,
)

logger = logging.getLogger("twitter_scraper.routes.scrape")

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared helper: write structured execution log entry
# ---------------------------------------------------------------------------

def _log_execution(
    username: str,
    batch: int,
    start_time: datetime,
    success: bool,
    count: int,
    error_msg: str = "",
) -> None:
    """
    Append a single structured line to the scraper execution metrics log.

    Args:
        username: Target handle that was scraped.
        batch: Batch index that was attempted.
        start_time: UTC datetime when the operation started.
        success: Whether the operation completed without error.
        count: Number of posts saved.
        error_msg: Human-readable failure reason (empty on success).
    """
    end_time = datetime.now(tz=timezone.utc)
    duration = (end_time - start_time).total_seconds()
    status_str = "SUCCESS" if success else f"FAILED ({error_msg})"
    entry = (
        f"[{start_time.isoformat()}] BATCH_OP | "
        f"Target: @{username} | Batch: {batch} | "
        f"Status: {status_str} | Posts: {count} | "
        f"Duration: {duration:.2f}s | Finished: {end_time.isoformat()}\n"
    )
    try:
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.SCRAPER_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(entry)
    except Exception as exc:
        logger.error("Failed to write execution log: %s", exc)


# ---------------------------------------------------------------------------
# Helper: translate provider exceptions → HTTP errors
# ---------------------------------------------------------------------------

def _handle_provider_error(
    exc: Exception,
    username: str,
    batch: int,
    start_time: datetime,
    live_progress: Dict[str, Any],
) -> HTTPException:
    """
    Map a provider-layer exception to the appropriate HTTP error code.

    Side-effects: updates ``live_progress`` and writes the execution log.

    Args:
        exc: The caught exception.
        username: Target handle (for logging).
        batch: Current batch number (for logging).
        start_time: Operation start time (for logging).
        live_progress: Shared mutable dict updated in place.

    Returns:
        A configured ``HTTPException`` ready to be raised by the route.
    """
    err_msg = str(exc)

    if isinstance(exc, AuthenticationError):
        live_progress["status"] = "Authentication Required"
        live_progress["error_message"] = err_msg
        _log_execution(username, batch, start_time, False, 0, "Authentication Required")
        return HTTPException(status_code=401, detail=err_msg)

    if isinstance(exc, (UserNotFoundError, AccountSuspendedError,
                         AccountProtectedError, RateLimitExceededError)):
        live_progress["status"] = "Failed"
        live_progress["error_message"] = err_msg
        _log_execution(username, batch, start_time, False, 0, err_msg)
        return HTTPException(status_code=400, detail=err_msg)

    # Generic provider or unexpected error.
    live_progress["status"] = "Error"
    live_progress["error_message"] = err_msg
    _log_execution(username, batch, start_time, False, 0, err_msg)
    return HTTPException(status_code=500, detail=f"Provider error: {err_msg}")


# ---------------------------------------------------------------------------
# POST /scrape/start
# ---------------------------------------------------------------------------

@router.post(
    "/scrape/start",
    response_model=ScrapeResponse,
    summary="Start a new scraping session (Batch 1)",
)
async def start_scrape(payload: ScrapeStartRequest) -> ScrapeResponse:
    """
    Reset any previous session and retrieve the first batch of posts.

    The username is sanitised (leading ``@`` stripped, whitespace trimmed)
    and validated to be non-empty. Any previously stored state is discarded
    before the new session begins.

    Args:
        payload: ``ScrapeStartRequest`` with the target username.

    Returns:
        ``ScrapeResponse`` with batch index, post count, and output filename.

    Raises:
        400: Invalid username or known platform error.
        401: Auth session missing or expired.
        409: Another scrape is already in progress.
        500: Unexpected provider failure.
    """
    from dependencies import provider, state_manager, file_manager, scrape_lock, live_progress

    username = payload.username.strip().lstrip("@")
    if not username:
        raise HTTPException(status_code=400, detail="Username must not be empty.")

    if scrape_lock.locked():
        raise HTTPException(status_code=409, detail="A scraping session is already in progress.")

    start_time = datetime.now(tz=timezone.utc)

    async with scrape_lock:
        # Reset any prior session state.
        state_manager.reset_state()

        live_progress.update({
            "status": "Scraping (Batch 1)…",
            "progress_message": "Initialising session…",
            "error_message": None,
        })

        async def _progress(msg: str) -> None:
            live_progress["progress_message"] = msg

        try:
            posts = await provider.fetch_posts(
                username=username,
                batch_number=1,
                last_post_id=None,
                progress_callback=_progress,
            )

            if not posts:
                raise ProviderError("No posts found — the timeline may be empty.")

            filename = file_manager.save_batch(username, 1, posts)
            last_post = posts[-1]

            new_state = ScraperState(
                username=username,
                batch=1,
                last_post_id=last_post.post_id,
                total_scraped=len(posts),
                latest_filename=filename,
            )
            state_manager.save_state(new_state)

            _log_execution(username, 1, start_time, True, len(posts))
            live_progress.update({
                "status": "Completed Successfully",
                "progress_message": "",
                "error_message": None,
            })

            return ScrapeResponse(
                message="First batch retrieved successfully.",
                batch=1,
                count=len(posts),
                filename=filename,
            )

        except Exception as exc:
            raise _handle_provider_error(exc, username, 1, start_time, live_progress)


# ---------------------------------------------------------------------------
# POST /scrape/next
# ---------------------------------------------------------------------------

@router.post(
    "/scrape/next",
    response_model=ScrapeResponse,
    summary="Continue retrieving the next batch",
)
async def scrape_next() -> ScrapeResponse:
    """
    Retrieve the next batch of posts for the active scraping session.

    Reads the persisted state to determine the target username, current
    batch index, and last-seen post ID. Uses the last post ID as a
    pagination cursor to avoid duplicate records.

    Returns:
        ``ScrapeResponse`` with updated batch index, post count, and filename.
        If the timeline is exhausted (no new posts), the response will have
        ``count=0`` and no filename.

    Raises:
        400: No active session or known platform error.
        401: Auth session missing or expired.
        409: Another scrape is already in progress.
        500: Unexpected provider failure.
    """
    from dependencies import provider, state_manager, file_manager, scrape_lock, live_progress

    if scrape_lock.locked():
        raise HTTPException(status_code=409, detail="A scraping session is already in progress.")

    state = state_manager.load_state()
    if not state:
        raise HTTPException(
            status_code=400,
            detail="No active scraping session. Use POST /scrape/start first.",
        )

    username = state.username
    next_batch = state.batch + 1
    start_time = datetime.now(tz=timezone.utc)

    async with scrape_lock:
        live_progress.update({
            "status": f"Scraping (Batch {next_batch})…",
            "progress_message": "Initialising session…",
            "error_message": None,
        })

        async def _progress(msg: str) -> None:
            live_progress["progress_message"] = msg

        try:
            posts = await provider.fetch_posts(
                username=username,
                batch_number=next_batch,
                last_post_id=state.last_post_id,
                progress_callback=_progress,
            )

            if not posts:
                live_progress.update({
                    "status": "Completed Successfully",
                    "progress_message": "Timeline exhausted — no more posts found.",
                    "error_message": None,
                })
                _log_execution(username, next_batch, start_time, True, 0, "Timeline exhausted")
                return ScrapeResponse(
                    message="Timeline exhausted — no additional posts found.",
                    batch=state.batch,
                    count=0,
                    filename=None,
                )

            filename = file_manager.save_batch(username, next_batch, posts)
            last_post = posts[-1]

            updated_state = ScraperState(
                username=username,
                batch=next_batch,
                last_post_id=last_post.post_id,
                total_scraped=state.total_scraped + len(posts),
                latest_filename=filename,
            )
            state_manager.save_state(updated_state)

            _log_execution(username, next_batch, start_time, True, len(posts))
            live_progress.update({
                "status": "Completed Successfully",
                "progress_message": "",
                "error_message": None,
            })

            return ScrapeResponse(
                message=f"Batch {next_batch} retrieved successfully.",
                batch=next_batch,
                count=len(posts),
                filename=filename,
            )

        except Exception as exc:
            raise _handle_provider_error(exc, username, next_batch, start_time, live_progress)


@router.post(
    "/scrape/latest",
    response_model=SpecialScrapeResponse,
    summary="Retrieve the single latest post (excluding pinned)",
)
async def scrape_latest(payload: ScrapeStartRequest) -> SpecialScrapeResponse:
    from dependencies import provider, file_manager, scrape_lock, live_progress

    username = payload.username.strip().lstrip("@")
    if not username:
        raise HTTPException(status_code=400, detail="Username must not be empty.")

    if scrape_lock.locked():
        raise HTTPException(status_code=409, detail="A scraping session is already in progress.")

    start_time = datetime.now(tz=timezone.utc)

    async with scrape_lock:
        live_progress.update({
            "status": "Fetching Latest Post…",
            "progress_message": "Initialising session…",
            "error_message": None,
        })

        async def _progress(msg: str) -> None:
            live_progress["progress_message"] = msg

        try:
            post = await provider.fetch_latest_post(
                username=username,
                progress_callback=_progress,
            )

            if not post:
                raise ProviderError("No posts found on the timeline.")

            filename = file_manager.save_special_post(username, post, "latest")

            _log_execution(username, 0, start_time, True, 1, "Fetched latest post")
            live_progress.update({
                "status": "Completed Successfully",
                "progress_message": "",
                "error_message": None,
            })

            return SpecialScrapeResponse(
                message="Latest post retrieved successfully.",
                filename=filename,
                post=post,
            )

        except Exception as exc:
            raise _handle_provider_error(exc, username, 0, start_time, live_progress)


