"""
models.py
=========
Pydantic data models used throughout the X (Twitter) Scraper application.

All models use strict typing and field-level documentation so that every
consumer of the data (API routes, file manager, provider layer) has a
single, authoritative definition of the data shapes.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core Output Model
# ---------------------------------------------------------------------------

class Post(BaseModel):
    """
    Normalised representation of a single scraped post (tweet).

    Every field maps 1-to-1 with the required JSON output specification.
    Fields that may not be available on every post default to safe values
    (0 for counts, empty list for collections, empty string for text).
    """

    post_id: str = Field(
        ...,
        description="Unique numeric identifier of the post (tweet ID string)."
    )
    username: str = Field(
        ...,
        description="@handle of the post author, without the leading '@'."
    )
    display_name: str = Field(
        ...,
        description="Public display name of the post author."
    )
    created_at: str = Field(
        ...,
        description="ISO 8601 datetime string when the post was published."
    )
    text: str = Field(
        "",
        description="Full plain-text content of the post."
    )
    url: str = Field(
        "",
        description="Permanent link to the post (e.g. https://x.com/user/status/123)."
    )
    reply_count: int = Field(
        0,
        description="Number of replies the post has received."
    )
    repost_count: int = Field(
        0,
        description="Number of reposts / retweets."
    )
    like_count: int = Field(
        0,
        description="Number of likes."
    )
    view_count: int = Field(
        0,
        description="Number of views (impressions). Zero when unavailable."
    )
    hashtags: List[str] = Field(
        default_factory=list,
        description="List of hashtag strings found in the post (without '#')."
    )
    mentions: List[str] = Field(
        default_factory=list,
        description="List of @mentioned usernames found in the post (without '@')."
    )
    media_urls: List[str] = Field(
        default_factory=list,
        description="List of media asset URLs (photos, video thumbnails/posters)."
    )
    external_links: List[str] = Field(
        default_factory=list,
        description="List of external hyperlinks found in the post text."
    )


# ---------------------------------------------------------------------------
# State / Persistence Models
# ---------------------------------------------------------------------------

class ScraperState(BaseModel):
    """
    Persisted cursor tracking the current scraping session.

    Written to ``state/state.json`` after every successful batch so that
    the application can resume from the correct position on the next request.
    """

    username: str = Field(
        ...,
        description="Target account handle currently being scraped."
    )
    batch: int = Field(
        0,
        description="Index of the most-recently completed batch (1-based)."
    )
    last_post_id: Optional[str] = Field(
        None,
        description="Post ID of the last item saved in the previous batch."
    )
    total_scraped: int = Field(
        0,
        description="Cumulative total of posts collected across all batches."
    )
    latest_filename: Optional[str] = Field(
        None,
        description="Filename of the most recently written JSON batch file."
    )


# ---------------------------------------------------------------------------
# API Response Models
# ---------------------------------------------------------------------------

class StatusResponse(BaseModel):
    """
    Response payload for ``GET /status``.

    Combines the persisted ScraperState with the in-memory live progress
    so the frontend always receives a complete snapshot in a single request.
    """

    username: Optional[str] = Field(None, description="Active target username.")
    batch: int = Field(0, description="Current batch number.")
    total_scraped: int = Field(0, description="Total posts collected so far.")
    last_file: Optional[str] = Field(None, description="Latest output filename.")
    status: str = Field("Idle", description="Human-readable status string.")
    progress_message: str = Field("", description="Live progress step message.")
    error_message: Optional[str] = Field(None, description="Latest error detail, if any.")


class ScrapeStartRequest(BaseModel):
    """Request payload for ``POST /scrape/start``."""

    username: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Target X (Twitter) username. Leading '@' is stripped automatically."
    )


class ScrapeResponse(BaseModel):
    """Successful response payload for scrape start/next endpoints."""

    message: str = Field(..., description="Human-readable result summary.")
    batch: int = Field(..., description="Batch number that was just completed.")
    count: int = Field(..., description="Number of posts saved in this batch.")
    filename: Optional[str] = Field(None, description="Output JSON filename.")


class SpecialScrapeResponse(BaseModel):
    """Successful response payload for scrape latest/oldest endpoints."""

    message: str = Field(..., description="Human-readable result summary.")
    filename: str = Field(..., description="Output JSON filename.")
    post: Post = Field(..., description="The fetched Post object data.")

