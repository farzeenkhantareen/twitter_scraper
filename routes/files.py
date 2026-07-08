"""
routes/files.py
===============
POST /reset         — Clear the active scraping session state.
GET  /download/latest — Serve the most recent scraped JSON file for download.
"""

import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger("twitter_scraper.routes.files")

router = APIRouter()


def _copy_to_downloaded_json(latest_file) -> None:
    """Copy the file to the downloaded_json directory in the project root."""
    import shutil
    import config
    try:
        downloaded_dir = config.BASE_DIR / "downloaded_json"
        downloaded_dir.mkdir(parents=True, exist_ok=True)
        dest_file = downloaded_dir / latest_file.name
        shutil.copy2(latest_file, dest_file)
        logger.info("Successfully copied %s to %s", latest_file.name, dest_file)
    except Exception as exc:
        logger.error("Failed to copy %s to downloaded_json: %s", latest_file.name, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to copy file to downloaded_json folder: {exc}"
        )


@router.post("/reset", summary="Reset scraping session progress")
async def reset_progress() -> dict:
    """
    Clear the persisted scraping state and reset the live progress tracker.

    Does **not** delete any previously saved JSON batch files — only the
    cursor state (``state/state.json``) is removed so a fresh session can
    begin with a different username or from the start of the same profile.

    Returns:
        JSON object with a confirmation message.

    Raises:
        409: A scrape is currently running (cannot reset mid-operation).
        500: State file deletion failed.
    """
    from dependencies import state_manager, scrape_lock, live_progress

    if scrape_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Cannot reset state while a scraping session is active.",
        )

    try:
        state_manager.reset_state()
        live_progress.update({
            "status": "Idle",
            "progress_message": "",
            "error_message": None,
        })
        logger.info("Scraper state reset successfully.")
        return {"message": "Scraping progress has been reset successfully."}
    except Exception as exc:
        logger.error("Failed to reset scraper state: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to reset state: {exc}")


@router.get("/download/latest", summary="Download the latest scraped JSON batch")
async def download_latest() -> FileResponse:
    """
    Locate and stream the most recently written JSON batch file.

    The file to serve is resolved from the persisted state (``latest_filename``
    field) or from the newest file in ``scraped_data/`` as a fallback.

    Returns:
        The JSON file as an ``application/json`` attachment download.

    Raises:
        404: No batch files exist yet.
    """
    from dependencies import state_manager, file_manager

    state = state_manager.load_state()
    latest_file = file_manager.get_latest_batch_file(state.username if state else None)

    if not latest_file or not latest_file.exists():
        raise HTTPException(
            status_code=404,
            detail="No scraped batch files are available for download.",
        )

    # Copy to downloaded_json folder
    _copy_to_downloaded_json(latest_file)

    return FileResponse(
        path=str(latest_file),
        media_type="application/json",
        filename=latest_file.name,
    )


@router.get("/download/latest-post", summary="Download the latest scraped post JSON")
async def download_latest_post() -> FileResponse:
    """
    Locate and stream the single latest post JSON file.

    Returns:
        The JSON file as an download attachment.

    Raises:
        404: No latest post file is available yet.
    """
    from dependencies import state_manager, file_manager

    state = state_manager.load_state()
    username = state.username if state else None
    
    if not username:
        # Fallback: find the newest *_latest.json in scraped_data/
        files = list(file_manager._scraped_data_dir.glob("*_latest.json"))
        if not files:
            raise HTTPException(
                status_code=404,
                detail="No latest post file is available for download.",
            )
        import os
        files.sort(key=os.path.getmtime, reverse=True)
        latest_file = files[0]
    else:
        latest_file = file_manager._scraped_data_dir / f"{username}_latest.json"

    if not latest_file.exists():
        raise HTTPException(
            status_code=404,
            detail="No latest post file is available for download.",
        )

    # Copy to downloaded_json folder
    _copy_to_downloaded_json(latest_file)

    return FileResponse(
        path=str(latest_file),
        media_type="application/json",
        filename=latest_file.name,
    )

