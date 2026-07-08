"""
provider/base.py
================
Abstract base class and shared exception hierarchy for data providers.

The rest of the application depends **only** on the ``DataProvider``
interface defined here. Switching to a different backend (official API,
third-party data service, mock, etc.) requires only a new concrete
subclass — no changes elsewhere.
"""

import logging
from abc import ABC, abstractmethod
from typing import Callable, Coroutine, List, Optional, Any

from models import Post

logger = logging.getLogger("twitter_scraper.provider")

# ---------------------------------------------------------------------------
# Provider Exception Hierarchy
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    """
    Base class for all data-provider errors.

    Catching this class is sufficient to handle any provider-specific
    failure without depending on the concrete implementation.
    """
    pass


class UserNotFoundError(ProviderError):
    """Raised when the requested username does not exist on the platform."""
    pass


class AccountSuspendedError(ProviderError):
    """Raised when the target account has been suspended by the platform."""
    pass


class AccountProtectedError(ProviderError):
    """
    Raised when the target account is private/protected.

    Only followers approved by the account owner can view its posts.
    """
    pass


class RateLimitExceededError(ProviderError):
    """
    Raised when the platform is temporarily refusing requests.

    The caller should wait before retrying.
    """
    pass


class AuthenticationError(ProviderError):
    """
    Raised when provider credentials are missing or invalid.

    The operator must reconfigure authentication before retrying.
    """
    pass


# ---------------------------------------------------------------------------
# Progress Callback Type Alias
# ---------------------------------------------------------------------------

#: Type signature for an async progress-reporting callback.
#: Receives a single human-readable step description string.
ProgressCallback = Optional[Callable[[str], Coroutine[Any, Any, None]]]


# ---------------------------------------------------------------------------
# Abstract Provider
# ---------------------------------------------------------------------------

class DataProvider(ABC):
    """
    Abstract interface that every data provider must implement.

    A provider is responsible for:
    - Authenticating with the underlying platform or service.
    - Paginating through a user's post timeline.
    - Returning normalised ``Post`` objects to the caller.
    - Handling and surfacing platform-specific errors as the shared
      exception hierarchy above.

    The application layer (routes, state manager, file manager) must never
    import or reference provider-specific details such as Playwright, HTTP
    client libraries, or API keys.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialise(self) -> None:
        """
        Perform any one-time setup required before fetching posts.

        Examples: start a browser session, open an HTTP client, obtain an
        OAuth token. Called once per application lifetime.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """
        Release all resources held by the provider.

        Called on application shutdown. Must be idempotent.
        """
        ...

    # ------------------------------------------------------------------
    # Core Data Fetching
    # ------------------------------------------------------------------

    @abstractmethod
    async def fetch_posts(
        self,
        username: str,
        batch_number: int,
        last_post_id: Optional[str] = None,
        progress_callback: ProgressCallback = None,
    ) -> List[Post]:
        """
        Retrieve a batch of posts from the target user's timeline.

        Args:
            username:
                The account handle to retrieve posts for (without '@').
            batch_number:
                1-based index of the current batch. Used for logging and
                any provider-specific cursor calculations.
            last_post_id:
                Opaque string identifier of the last post returned in the
                previous batch. ``None`` on the first call. The provider
                must return only posts *older* than this post (i.e. the
                next page).
            progress_callback:
                Optional async callable that accepts a single ``str``
                describing the current step. Implementations should call
                this frequently so the UI can display live progress.

        Returns:
            A list of normalised ``Post`` objects. An empty list signals
            that the timeline has been exhausted.

        Raises:
            UserNotFoundError: The username does not exist.
            AccountSuspendedError: The account has been suspended.
            AccountProtectedError: The account is private/protected.
            RateLimitExceededError: The platform is rate-limiting requests.
            AuthenticationError: Provider credentials are missing/invalid.
            ProviderError: Any other provider-level failure.
        """
        ...

    @abstractmethod
    async def fetch_latest_post(
        self,
        username: str,
        progress_callback: ProgressCallback = None,
    ) -> Optional[Post]:
        """
        Retrieve the single newest post on the user's timeline (excluding pinned posts).

        Args:
            username: The account handle to retrieve posts for (without '@').
            progress_callback: Optional progress reporter callback.

        Returns:
            A single normalised Post object, or None if no posts exist.
        """
        ...


