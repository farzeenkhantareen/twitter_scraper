"""
session.py
==========
DEPRECATED — kept for backward compatibility only.

The browser session management previously handled here has been moved into
``provider/playwright_provider.py`` as the private ``_BrowserSession`` class.

This file exists solely to avoid import errors if any external scripts
reference ``session.SessionManager`` or ``session.AuthenticationRequiredError``.
New code should import from ``provider`` directly.
"""

# Re-export for backward compatibility.
from provider.base import AuthenticationError as AuthenticationRequiredError  # noqa: F401

import logging

logger = logging.getLogger("twitter_scraper.session")
logger.warning(
    "session.py is deprecated. Use provider.PlaywrightProvider instead."
)
