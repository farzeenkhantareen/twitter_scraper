"""
file_manager.py
===============
Handles all file system I/O for the X (Twitter) Scraper application.

Responsibilities:
  - Ensure required directories exist at startup.
  - Serialise ``Post`` objects to JSON batch files with sequential names.
  - Retrieve the path to the latest or a specific batch file.
  - Return the path to the authentication session file.

All paths are resolved relative to ``config.BASE_DIR`` and all filename
patterns come from ``config.BATCH_FILENAME_PATTERN`` so nothing is
hardcoded in this module.
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

import config
from models import Post

logger = logging.getLogger("twitter_scraper.file_manager")


class FileManager:
    """
    File system helper for the scraper application.

    All write operations create parent directories automatically and use
    UTF-8 encoding with ``ensure_ascii=False`` to preserve non-Latin
    characters in post content.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        """
        Initialise the FileManager and create required directories.

        Args:
            base_dir: Project root directory. Defaults to ``config.BASE_DIR``.
        """
        self._base_dir = Path(base_dir) if base_dir else config.BASE_DIR
        self._scraped_data_dir = self._base_dir / "scraped_data"
        self._sessions_dir = self._base_dir / "sessions"
        self._state_dir = self._base_dir / "state"
        self._logs_dir = self._base_dir / "logs"
        self._ensure_directories()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _ensure_directories(self) -> None:
        """
        Create all required application directories if they do not exist.

        Raises:
            OSError: If any directory cannot be created.
        """
        dirs = [
            self._scraped_data_dir,
            self._sessions_dir,
            self._state_dir,
            self._logs_dir,
        ]
        for directory in dirs:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                logger.error("Failed to create directory %s: %s", directory, exc, exc_info=True)
                raise OSError(f"Cannot create required directory {directory}: {exc}") from exc
        logger.debug("All required directories are present.")

    # ------------------------------------------------------------------
    # Write Operations
    # ------------------------------------------------------------------

    def save_batch(self, username: str, batch_number: int, posts: List[Post]) -> str:
        """
        Serialise a list of posts and write them to a sequentially-named JSON file.

        The filename follows the pattern defined in ``config.BATCH_FILENAME_PATTERN``
        (default: ``{username}_batch_{batch_number:03d}.json``).

        Args:
            username: The scraped account handle (used in the filename).
            batch_number: 1-based batch index (zero-padded to 3 digits).
            posts: List of normalised ``Post`` objects to serialise.

        Returns:
            The filename (basename only, not full path) of the saved file.

        Raises:
            IOError: If the file cannot be written.
        """
        filename = config.BATCH_FILENAME_PATTERN.format(
            username=username,
            batch_number=batch_number,
        )
        filepath = self._scraped_data_dir / filename

        try:
            data = [post.model_dump() for post in posts]
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=4)
            logger.info("Saved %d posts to %s", len(posts), filepath)
            return filename
        except Exception as exc:
            logger.error("Failed to write batch file %s: %s", filepath, exc, exc_info=True)
            raise IOError(f"Could not write batch file {filename}: {exc}") from exc

    # ------------------------------------------------------------------
    # Read / Query Operations
    # ------------------------------------------------------------------

    def get_latest_batch_file(self, username: Optional[str] = None) -> Optional[Path]:
        """
        Find the path to the most recently modified JSON batch file.

        Args:
            username: Optional filter to restrict results to a specific account.
                      When ``None``, all ``.json`` files in ``scraped_data/``
                      are considered.

        Returns:
            Absolute ``Path`` to the newest batch file, or ``None`` if no
            files are found.
        """
        try:
            if not self._scraped_data_dir.exists():
                return None

            pattern = f"{username}_batch_*.json" if username else "*.json"
            files = list(self._scraped_data_dir.glob(pattern))

            if not files:
                return None

            # Sort by modification time — newest first.
            files.sort(key=os.path.getmtime, reverse=True)
            return files[0]

        except Exception as exc:
            logger.error("Error locating latest batch file: %s", exc, exc_info=True)
            return None

    def list_all_batches(self, username: str) -> List[Path]:
        """
        Return all batch files for a given username, sorted by batch number.

        Args:
            username: The account handle to list batch files for.

        Returns:
            List of ``Path`` objects sorted in ascending batch order.
        """
        try:
            files = list(self._scraped_data_dir.glob(f"{username}_batch_*.json"))
            files.sort(key=lambda p: p.name)
            return files
        except Exception as exc:
            logger.error("Error listing batch files for @%s: %s", username, exc, exc_info=True)
            return []

    def get_auth_session_path(self) -> Path:
        """
        Return the path to the Playwright authentication session file.

        Returns:
            Absolute ``Path`` to ``sessions/auth.json``.
        """
        return self._sessions_dir / "auth.json"

    def save_special_post(self, username: str, post: Post, post_type: str) -> str:
        """
        Save a single post (e.g. latest, oldest) to a JSON file.

        Args:
            username: The scraped account handle.
            post: The Post object to save.
            post_type: Either 'latest' or 'oldest'.

        Returns:
            The filename of the saved file.
        """
        filename = f"{username}_{post_type}.json"
        filepath = self._scraped_data_dir / filename

        try:
            data = post.model_dump()
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=4)
            logger.info("Saved special %s post for @%s to %s", post_type, username, filepath)
            return filename
        except Exception as exc:
            logger.error("Failed to write special post file %s: %s", filepath, exc, exc_info=True)
            raise IOError(f"Could not write special post file {filename}: {exc}") from exc

