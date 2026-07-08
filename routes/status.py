"""
routes/status.py
================
GET /status — Returns a combined snapshot of persistent state and live
in-memory progress so the frontend can display a complete dashboard with
a single request.
"""

import logging
from fastapi import APIRouter
from models import StatusResponse

logger = logging.getLogger("twitter_scraper.routes.status")

router = APIRouter()


@router.get("/status", response_model=StatusResponse, summary="Get current scraper status")
async def get_status() -> StatusResponse:
    """
    Return the current scraper state and live progress metrics.

    This endpoint is polled by the frontend during active scraping sessions
    (every ~1 second) to display real-time step messages, and is also called
    on page load to restore the dashboard from persistent state.

    Returns:
        ``StatusResponse`` containing username, batch index, total posts
        collected, latest filename, human-readable status string, live
        progress message, and any error detail.
    """
    from dependencies import state_manager, file_manager, live_progress

    state = state_manager.load_state()
    latest_file = file_manager.get_latest_batch_file(state.username if state else None)

    return StatusResponse(
        username=state.username if state else None,
        batch=state.batch if state else 0,
        total_scraped=state.total_scraped if state else 0,
        last_file=state.latest_filename if state else (latest_file.name if latest_file else None),
        status=live_progress["status"],
        progress_message=live_progress["progress_message"],
        error_message=live_progress["error_message"],
    )
