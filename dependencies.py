"""
dependencies.py
===============
Application-wide singleton instances and shared mutable state.

This module is the single source of truth for objects that must be shared
across the routes package without circular imports. Routes import directly
from here rather than from ``app.py``.

Design:
    Using module-level singletons (rather than FastAPI's Depends() injection)
    keeps the architecture simple for this single-process, single-worker
    application. If the app is ever scaled to multiple workers, these should
    be replaced with a distributed state backend (Redis, etc.).
"""

import asyncio
from typing import Any, Dict

from file_manager import FileManager
from state_manager import StateManager
from provider.playwright_provider import PlaywrightProvider
import config

# ---------------------------------------------------------------------------
# Module singletons — initialised once at import time
# ---------------------------------------------------------------------------

#: Central file I/O helper.
file_manager: FileManager = FileManager(base_dir=config.BASE_DIR)

#: Persistent state tracker (reads/writes state/state.json).
state_manager: StateManager = StateManager(base_dir=config.BASE_DIR)

#: Concrete data provider (Playwright-backed).
provider: PlaywrightProvider = PlaywrightProvider()

#: Global asyncio lock — ensures only one scrape runs at a time.
scrape_lock: asyncio.Lock = asyncio.Lock()

#: In-memory live progress updated by route handlers, read by /status.
live_progress: Dict[str, Any] = {
    "status": "Idle",
    "progress_message": "",
    "error_message": None,
}
