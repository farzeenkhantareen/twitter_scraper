"""
state_manager.py
================
Reads, writes, and resets the JSON progress state file (``state/state.json``).

The state file tracks the active scraping session across HTTP requests:
  - Target username
  - Current batch index
  - Last post ID (pagination cursor)
  - Total posts collected
  - Latest output filename

The ``StateManager`` keeps an in-memory cache so repeated reads within a
single request cycle do not hit the filesystem. The cache is invalidated
whenever the state is saved or reset.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from models import ScraperState
import config

logger = logging.getLogger("twitter_scraper.state_manager")


class StateManager:
    """
    Manages reading, writing, and resetting the JSON scraping progress state.

    The state is persisted as a single JSON file so that the application
    can survive server restarts without losing its pagination cursor.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        """
        Initialise the StateManager.

        Args:
            base_dir: Project root directory. Defaults to ``config.BASE_DIR``.
        """
        self._base_dir = Path(base_dir) if base_dir else config.BASE_DIR
        self._state_file = self._base_dir / "state" / "state.json"
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Optional[ScraperState] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_state(self) -> Optional[ScraperState]:
        """
        Load the current ``ScraperState`` from disk, or ``None`` if absent.

        Uses an in-memory cache to avoid repeated filesystem reads within
        the same request. The cache is cleared on ``save_state`` or
        ``reset_state``.

        Returns:
            A populated ``ScraperState``, or ``None`` if no state exists
            or the file is corrupted.
        """
        if self._cache is not None:
            return self._cache

        if not self._state_file.exists():
            logger.debug("State file does not exist — returning None.")
            return None

        try:
            with open(self._state_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            if not data or not isinstance(data, dict):
                logger.warning("State file is empty or malformed — treating as absent.")
                return None

            self._cache = ScraperState(**data)
            logger.debug("Loaded state from disk: %s", self._cache.model_dump())
            return self._cache

        except json.JSONDecodeError:
            logger.warning("Corrupted JSON in state.json — ignoring existing state.")
            return None
        except Exception as exc:
            logger.error("Unexpected error reading state file: %s", exc, exc_info=True)
            return None

    def save_state(self, state: ScraperState) -> None:
        """
        Persist a ``ScraperState`` to disk and update the in-memory cache.

        Args:
            state: The state object to save.

        Raises:
            IOError: If the file cannot be written.
        """
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._state_file, "w", encoding="utf-8") as fh:
                json.dump(state.model_dump(), fh, ensure_ascii=False, indent=4)
            self._cache = state
            logger.debug("Saved state: %s", state.model_dump())
        except Exception as exc:
            logger.error("Failed to save state to %s: %s", self._state_file, exc, exc_info=True)
            raise IOError(f"Could not write state file: {exc}") from exc

    def reset_state(self) -> None:
        """
        Delete the state file and clear the in-memory cache.

        Safe to call even if the file does not exist.

        Raises:
            IOError: If the file exists but cannot be deleted.
        """
        self._cache = None  # Always clear cache first.
        try:
            if self._state_file.exists():
                self._state_file.unlink()
                logger.info("State file deleted: %s", self._state_file)
            else:
                logger.debug("State file did not exist — reset is a no-op.")
        except Exception as exc:
            logger.error("Failed to delete state file: %s", exc, exc_info=True)
            raise IOError(f"Could not reset state file: {exc}") from exc
